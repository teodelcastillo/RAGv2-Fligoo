#!/usr/bin/env bash

python manage.py collectstatic --noinput

echo "[run] runserver with django"
gunicorn main.wsgi:application --bind 0.0.0.0:8000 --log-level=info --timeout=500