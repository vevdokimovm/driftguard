#!/bin/sh
# запуск демо-приложения
exec python -m http.server 8080 --directory /srv/app
