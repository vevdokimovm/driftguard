"""Сквозная проверка стенда docker compose: дрейф находится, уходит после отката и принимается как эталон.

запуск (стенд уже поднят): python3 demo/smoke.py [--server http://127.0.0.1:8000]
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

TIMEOUT = 60


class Stand:
    """Доступ к API сервера и к контейнерам «машин»."""

    def __init__(self, server: str, token: str) -> None:
        self.base = server.rstrip("/") + "/api"
        self.headers = {"X-API-Token": token} if token else {}

    def call(self, method: str, path: str):
        req = urllib.request.Request(self.base + path, method=method, headers=self.headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read()
            return json.loads(body) if body else None

    def hosts(self) -> dict:
        return {h["name"]: h for h in self.call("GET", "/hosts")}

    def wait(self, what: str, check) -> dict:
        """Ждёт, пока состояние хостов не удовлетворит условию; агенты шлют снимки раз в 5 с."""
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            hosts = self.hosts()
            if check(hosts):
                print(f"ok: {what} -> " + ", ".join(f"{n}={h['state']}/{h['changes']}" for n, h in hosts.items()))
                return hosts
            time.sleep(1)
        sys.exit(f"FAIL: {what}, last state: {self.hosts()}")

    @staticmethod
    def scenario(node: str, action: str) -> None:
        subprocess.run(["docker", "compose", "exec", "-T", node, "drift_scenario.sh", action], check=True)


def state(hosts: dict, name: str) -> str:
    return hosts.get(name, {}).get("state", "absent")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    stand = Stand(args.server, os.environ.get("API_TOKEN", ""))

    stand.wait("both nodes registered with auto baseline",
               lambda h: state(h, "node-a") == "OK" and state(h, "node-b") == "OK")
    stand.scenario("node-b", "apply")
    hosts = stand.wait("drift on node-b only", lambda h: state(h, "node-b") == "DRIFT" and h["node-b"]["changes"] == 4)
    assert state(hosts, "node-a") == "OK"
    kinds = {c["section"] for c in stand.call("GET", f"/hosts/{hosts['node-b']['id']}/drift")}
    assert kinds == {"files", "packages", "ports"}, kinds

    stand.scenario("node-b", "revert")
    stand.wait("node-b back to baseline after revert", lambda h: state(h, "node-b") == "OK")

    stand.scenario("node-b", "apply")
    hosts = stand.wait("drift again", lambda h: state(h, "node-b") == "DRIFT")
    stand.call("POST", f"/hosts/{hosts['node-b']['id']}/baseline")
    stand.wait("drift accepted as new baseline", lambda h: state(h, "node-b") == "OK")

    events = [e["kind"] for e in stand.call("GET", "/events?limit=20")]
    for kind in ("baseline_accepted", "drift_detected", "drift_resolved"):
        assert kind in events, (kind, events)
    print("smoke passed")


if __name__ == "__main__":
    main()
