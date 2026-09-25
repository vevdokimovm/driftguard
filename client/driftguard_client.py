"""Настольный клиент DriftGuard на Tkinter. Вся логика на сервере, клиент только вызывает API.

запуск: python driftguard_client.py [--server http://127.0.0.1:8000] [--token TOKEN]
"""

import argparse
import json
import os
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import messagebox, ttk

REFRESH_MS = 3000
STATE_COLORS = {"OK": "#1b7f3b", "DRIFT": "#c62828", "NO_BASELINE": "#8a6d00", "STALE": "#6b6b6b"}
KIND_COLORS = {"added": "#1b5e9f", "removed": "#c62828", "changed": "#8a4b00"}
EVENT_NAMES = {"drift_detected": "дрейф", "drift_resolved": "вернулся к эталону",
               "baseline_accepted": "принят эталон"}


class ApiClient:
    """Обёртка над API сервера: запросы и ответы в JSON."""

    def __init__(self, base_url: str, token: str = "") -> None:
        self.base = base_url.rstrip("/") + "/api"
        self.headers = {"Content-Type": "application/json"}
        if token:
            self.headers["X-API-Token"] = token

    def _call(self, method: str, path: str):
        req = urllib.request.Request(self.base + path, method=method, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            detail = json.loads(exc.read() or b"{}").get("detail", exc.reason)
            raise RuntimeError(f"{exc.code}: {detail}") from exc

    def hosts(self) -> list[dict]:
        return self._call("GET", "/hosts")

    def drift(self, host_id: int) -> list[dict]:
        return self._call("GET", f"/hosts/{host_id}/drift")

    def accept(self, host_id: int) -> dict:
        return self._call("POST", f"/hosts/{host_id}/baseline")

    def delete(self, host_id: int) -> None:
        self._call("DELETE", f"/hosts/{host_id}")

    def events(self) -> list[dict]:
        return self._call("GET", "/events?limit=100")

    def audit(self) -> list[dict]:
        return self._call("GET", "/audit?limit=100")


class DriftGuardApp(tk.Tk):
    """Главное окно: хосты сверху, снизу вкладки с расхождениями, событиями и журналом."""

    def __init__(self, api: ApiClient) -> None:
        super().__init__()
        self.api = api
        self.host_names: dict[int, str] = {}
        self.title("DriftGuard — контроль дрейфа конфигурации")
        self.geometry("1180x700")
        self._build()
        self.refresh()

    def _build(self) -> None:
        bar = ttk.Frame(self, padding=(10, 10, 10, 0))
        bar.pack(fill="x")
        ttk.Button(bar, text="Обновить", command=self.refresh_now).pack(side="left")
        ttk.Button(bar, text="Принять как эталон", command=self.accept_baseline).pack(side="left", padx=8)
        ttk.Button(bar, text="Удалить хост", command=self.delete_host).pack(side="left")

        self.hosts = self._table(self, ("name", "state", "changes", "seen", "baseline", "by", "ip"),
                                 ("Хост", "Состояние", "Расхождений", "Последний снимок", "Эталон принят",
                                  "Кем", "IP агента"), (130, 110, 100, 170, 170, 120, 130), height=7)
        for state, color in STATE_COLORS.items():
            self.hosts.tag_configure(state, foreground=color)
        self.hosts.master.pack(fill="x", padx=10, pady=8)
        self.hosts.bind("<<TreeviewSelect>>", lambda _: self.show_drift())

        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=10)
        self.drift = self._table(tabs, ("section", "key", "kind", "expected", "actual"),
                                 ("Раздел", "Что", "Изменение", "В эталоне", "Сейчас"), (90, 360, 100, 260, 260))
        for kind, color in KIND_COLORS.items():
            self.drift.tag_configure(kind, foreground=color)
        self.events = self._table(tabs, ("time", "host", "kind", "changes", "details"),
                                  ("Время (UTC)", "Хост", "Событие", "Расхождений", "Подробности"),
                                  (160, 130, 160, 100, 500))
        self.audit = self._table(tabs, ("time", "ip", "action", "details"),
                                 ("Время (UTC)", "IP", "Действие", "Подробности"), (160, 130, 160, 600))
        tabs.add(self.drift.master, text="Расхождения с эталоном")
        tabs.add(self.events.master, text="События дрейфа")
        tabs.add(self.audit.master, text="Журнал действий")

        self.status_bar = ttk.Label(self, text="", anchor="w")
        self.status_bar.pack(fill="x", padx=10, pady=8)

    @staticmethod
    def _table(parent, cols, heads, widths, height=12) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        table = ttk.Treeview(frame, columns=cols, show="headings", height=height)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=scroll.set)
        for c, h, w in zip(cols, heads, widths):
            table.heading(c, text=h)
            table.column(c, width=w, anchor="w")
        table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return table

    def selected_host(self) -> int | None:
        selected = self.hosts.selection()
        return int(selected[0]) if selected else None

    def refresh(self) -> None:
        """Обновляет все таблицы и сам ставит следующее обновление."""
        self.refresh_now()
        self.after(REFRESH_MS, self.refresh)

    def refresh_now(self) -> None:
        try:
            rows = self.api.hosts()
            selected = self.selected_host()
            self.hosts.delete(*self.hosts.get_children())
            self.host_names = {r["id"]: r["name"] for r in rows}
            for r in rows:
                self.hosts.insert("", "end", iid=str(r["id"]), tags=(r["state"],), values=(
                    r["name"], r["state"], r["changes"], _time(r["last_seen_at"]), _time(r["baseline_accepted_at"]),
                    r["baseline_accepted_by"] or "—", r["agent_ip"] or "—"))
            if selected is not None and self.hosts.exists(str(selected)):
                self.hosts.selection_set(str(selected))
            self._fill(self.events, [(_time(e["created_at"]), self.host_names.get(e["host_id"], e["host_id"]),
                                      EVENT_NAMES.get(e["kind"], e["kind"]), e["changes"], e["details"])
                                     for e in self.api.events()])
            self._fill(self.audit, [(_time(a["created_at"]), a["client_ip"], a["action"], a["details"])
                                    for a in self.api.audit()])
            self.show_drift()
            drifting = sum(r["state"] == "DRIFT" for r in rows)
            self.status_bar.config(text=f"Сервер: {self.api.base} · хостов: {len(rows)} · с дрейфом: {drifting} · "
                                        f"автообновление каждые {REFRESH_MS // 1000} с")
        except (OSError, RuntimeError) as exc:
            self.status_bar.config(text=f"Нет связи с сервером: {exc}")

    def show_drift(self) -> None:
        host_id = self.selected_host()
        if host_id is None:
            self._fill(self.drift, [])
            return
        try:
            changes = self.api.drift(host_id)
        except (OSError, RuntimeError) as exc:
            self.status_bar.config(text=f"Ошибка: {exc}")
            return
        self.drift.delete(*self.drift.get_children())
        for c in changes:
            self.drift.insert("", "end", tags=(c["kind"],), values=(
                c["section"], c["key"], c["kind"], c["expected"] or "—", c["actual"] or "—"))

    def accept_baseline(self) -> None:
        host_id = self.selected_host()
        if host_id is None:
            messagebox.showinfo("Эталон", "Выберите хост в таблице")
            return
        name = self.host_names.get(host_id, host_id)
        if messagebox.askyesno("Эталон", f"Признать текущую конфигурацию {name} правильной и сделать её эталоном?"):
            try:
                self.api.accept(host_id)
                self.refresh_now()
            except (OSError, RuntimeError) as exc:
                messagebox.showerror("Ошибка", str(exc))

    def delete_host(self) -> None:
        host_id = self.selected_host()
        if host_id is not None and messagebox.askyesno("Удаление", "Удалить хост вместе со снимками и событиями?"):
            try:
                self.api.delete(host_id)
                self.refresh_now()
            except (OSError, RuntimeError) as exc:
                messagebox.showerror("Ошибка", str(exc))

    @staticmethod
    def _fill(table: ttk.Treeview, rows: list[tuple]) -> None:
        table.delete(*table.get_children())
        for row in rows:
            table.insert("", "end", values=row)


def _time(value: str | None) -> str:
    return (value or "—")[:19].replace("T", " ")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=os.environ.get("DRIFTGUARD_API_TOKEN", ""),
                        help="value of X-API-Token if the server requires it")
    args = parser.parse_args()
    DriftGuardApp(ApiClient(args.server, args.token)).mainloop()


if __name__ == "__main__":
    main()
