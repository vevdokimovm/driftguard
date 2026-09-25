"""Расчёт дрейфа: сравнение снимка с эталоном. Чистые функции без БД и сети.

Снимок — словарь из трёх разделов:
    files    {путь: {"sha256": ..., "mode": "0644", "owner": "root:root"}}
    packages {имя пакета: версия}
    ports    ["tcp/22", "tcp/8080", ...]
"""

import hashlib
import json
from dataclasses import asdict, dataclass

SECTIONS = ("files", "packages", "ports")
FILE_FIELDS = ("sha256", "mode", "owner")


@dataclass(frozen=True)
class Change:
    """Одно расхождение с эталоном."""

    section: str
    key: str
    kind: str  # added | removed | changed
    expected: str | None
    actual: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def normalize(snapshot: dict) -> dict:
    """Оставляет только известные разделы, порты сортирует — от этого зависит отпечаток."""
    return {
        "files": dict(snapshot.get("files", {})),
        "packages": dict(snapshot.get("packages", {})),
        "ports": sorted(set(snapshot.get("ports", []))),
    }


def digest(snapshot: dict) -> str:
    """Отпечаток снимка: sha256 канонического JSON. Одинаковые конфигурации дают одинаковый отпечаток."""
    canonical = json.dumps(normalize(snapshot), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def compare(baseline: dict, actual: dict) -> list[Change]:
    """Все расхождения снимка с эталоном, в порядке раздел → ключ."""
    base, cur = normalize(baseline), normalize(actual)
    return _files(base["files"], cur["files"]) + _mapping("packages", base["packages"], cur["packages"]) \
        + _ports(base["ports"], cur["ports"])


def _files(base: dict, cur: dict) -> list[Change]:
    out = []
    for path in sorted(base.keys() | cur.keys()):
        if path not in cur:
            out.append(Change("files", path, "removed", _short(base[path]), None))
        elif path not in base:
            out.append(Change("files", path, "added", None, _short(cur[path])))
        else:
            for field in FILE_FIELDS:
                was, now = base[path].get(field), cur[path].get(field)
                if was != now:
                    out.append(Change("files", f"{path} [{field}]", "changed", was, now))
    return out


def _mapping(section: str, base: dict, cur: dict) -> list[Change]:
    out = []
    for key in sorted(base.keys() | cur.keys()):
        was, now = base.get(key), cur.get(key)
        if was != now:
            kind = "added" if was is None else "removed" if now is None else "changed"
            out.append(Change(section, key, kind, was, now))
    return out


def _ports(base: list, cur: list) -> list[Change]:
    removed = [Change("ports", p, "removed", p, None) for p in base if p not in cur]
    added = [Change("ports", p, "added", None, p) for p in cur if p not in base]
    return sorted(removed + added, key=lambda c: c.key)


def _short(entry: dict) -> str:
    """Краткая запись о файле для колонки «было/стало»."""
    return f"{entry.get('mode', '?')} {entry.get('owner', '?')} {str(entry.get('sha256', ''))[:12]}"


def summary(changes: list[Change]) -> str:
    """Строка для журнала событий: сколько расхождений в каком разделе."""
    counts = {s: sum(c.section == s for c in changes) for s in SECTIONS}
    return ", ".join(f"{s}: {n}" for s, n in counts.items() if n) or "нет расхождений"
