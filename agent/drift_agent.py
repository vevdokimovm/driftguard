"""Агент DriftGuard: снимает конфигурацию машины и отправляет её на сервер. Сравнением не занимается.

Только стандартная библиотека, чтобы агент запускался на любой машине без установки зависимостей.
запуск: python drift_agent.py --server http://127.0.0.1:8000 --watch /etc/passwd --watch /etc/ssh/sshd_config
"""

import argparse
import grp
import hashlib
import json
import logging
import os
import pwd
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from importlib import metadata
from pathlib import Path

logger = logging.getLogger("driftguard-agent")

# состояние сокета «слушает» в /proc/net/tcp — 0A
TCP_LISTEN = "0A"
# встроенный DNS Docker (127.0.0.11) слушает случайный порт, после перезапуска контейнера он другой — это не дрейф
IGNORED_ADDRESSES = {"0B00007F"}


class Collector:
    """Собирает три раздела снимка: файлы, пакеты, слушающие порты."""

    def __init__(self, watch: list[str], proc_net: str = "/proc/net") -> None:
        self.watch = watch
        self.proc_net = Path(proc_net)

    def snapshot(self, hostname: str) -> dict:
        return {"hostname": hostname, "files": self.files(), "packages": self.packages(), "ports": self.ports()}

    def files(self) -> dict:
        """sha256, права и владелец каждого отслеживаемого файла; каталоги обходятся рекурсивно."""
        out = {}
        for entry in self.watch:
            root = Path(entry)
            paths = sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else [root]
            for path in paths:
                try:
                    out[str(path)] = file_state(path)
                except OSError as exc:  # файл удалён или нет прав — в снимок не попадает, на сервере это «removed»
                    logger.debug("skip %s: %s", path, exc)
        return out

    def packages(self) -> dict:
        """Пакеты ОС из dpkg; если dpkg нет (не Debian), пакеты Python окружения агента."""
        if shutil.which("dpkg-query"):
            result = subprocess.run(["dpkg-query", "-W", "-f", "${Package}\t${Version}\n"],
                                    capture_output=True, text=True, check=True, timeout=30)
            return dict(line.split("\t", 1) for line in result.stdout.splitlines() if "\t" in line)
        return {f"py:{d.metadata['Name'].lower()}": d.version for d in metadata.distributions()}

    def ports(self) -> list[str]:
        """Слушающие TCP-порты из /proc/net/tcp и tcp6 (Linux); на других ОС раздел пустой."""
        found = set()
        for name in ("tcp", "tcp6"):
            table = self.proc_net / name
            if table.exists():
                found |= parse_proc_net(table.read_text())
        return sorted(f"tcp/{p}" for p in found)


def file_state(path: Path) -> dict:
    info = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return {"sha256": digest.hexdigest(), "mode": f"{stat.S_IMODE(info.st_mode):04o}",
            "owner": f"{_user(info.st_uid)}:{_group(info.st_gid)}"}


def parse_proc_net(text: str) -> set[int]:
    """Номера портов в состоянии LISTEN из таблицы /proc/net/tcp*: адрес вида 0100007F:1F90, порт в hex."""
    ports = set()
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) > 3 and fields[3] == TCP_LISTEN:
            address, port = fields[1].rsplit(":", 1)
            if address not in IGNORED_ADDRESSES:
                ports.add(int(port, 16))
    return ports


def _user(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def _group(gid: int) -> str:
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


class Sender:
    """Отправляет снимок на сервер."""

    def __init__(self, server: str, token: str = "") -> None:
        self.url = server.rstrip("/") + "/api/snapshots"
        self.headers = {"Content-Type": "application/json"}
        if token:
            self.headers["X-Agent-Token"] = token

    def send(self, snapshot: dict) -> dict:
        req = urllib.request.Request(self.url, data=json.dumps(snapshot).encode(), method="POST",
                                     headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{exc.code}: {exc.read().decode(errors='replace')[:300]}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="DriftGuard agent")
    parser.add_argument("--server", default=os.environ.get("DRIFTGUARD_SERVER", "http://127.0.0.1:8000"))
    parser.add_argument("--name", default=os.environ.get("DRIFTGUARD_HOSTNAME", socket.gethostname()))
    parser.add_argument("--watch", action="append", default=[], help="file or directory, can repeat")
    parser.add_argument("--interval", type=float, default=float(os.environ.get("DRIFTGUARD_INTERVAL", 0)),
                        help="seconds between snapshots; 0 — send once and exit")
    parser.add_argument("--token", default=os.environ.get("AGENT_TOKEN", ""))
    args = parser.parse_args()
    watch = args.watch or [p for p in os.environ.get("DRIFTGUARD_WATCH", "").split(":") if p]

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    collector, sender = Collector(watch), Sender(args.server, args.token)
    while True:
        try:
            ack = sender.send(collector.snapshot(args.name))
            logger.info("%s: state=%s changes=%s stored=%s", args.name, ack["state"], ack["changes"], ack["stored"])
        except (OSError, RuntimeError) as exc:  # сервер недоступен — агент не падает, пробует на следующем шаге
            logger.error("send failed: %s", exc)
            if not args.interval:
                sys.exit(1)
        if not args.interval:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
