#!/bin/sh
# Сценарий дрейфа на «машине»: то, что обычно делают руками в обход конфигурации.
#   drift_scenario.sh apply  — правка конфига, chmod 777 скрипта, лишний порт, обновление пакета
#   drift_scenario.sh revert — вернуть всё как было (сервер отметит, что хост вернулся к эталону)
set -e
case "$1" in
  apply)
    sed -i 's/^max_connections = .*/max_connections = 1000/' /srv/app/app.conf
    echo "debug = true" >> /srv/app/app.conf
    chmod 0777 /srv/app/run.sh
    python -m http.server 9999 >/dev/null 2>&1 &
    echo $! > /tmp/rogue.pid
    dpkg -i /opt/debs/demo-tool_1.1_all.deb >/dev/null
    echo "drift applied"
    ;;
  revert)
    cp /opt/golden/app.conf /srv/app/app.conf
    chmod 0755 /srv/app/run.sh
    [ -f /tmp/rogue.pid ] && kill "$(cat /tmp/rogue.pid)" && rm /tmp/rogue.pid
    dpkg -i /opt/debs/demo-tool_1.0_all.deb >/dev/null
    echo "drift reverted"
    ;;
  *)
    echo "usage: $0 apply|revert" >&2
    exit 2
    ;;
esac
