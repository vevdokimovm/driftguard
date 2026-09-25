#!/bin/sh
# Запуск «машины»: приложение слушает 8080, агент раз в DRIFTGUARD_INTERVAL секунд шлёт снимок на сервер.
set -e
python -m http.server 8080 --directory /srv/app >/dev/null 2>&1 &
exec python /opt/driftguard/drift_agent.py
