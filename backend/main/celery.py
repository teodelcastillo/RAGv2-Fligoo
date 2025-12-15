from __future__ import annotations
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "main.settings.prod")

app = Celery("proj")
# Read all CELERY_* settings from Django settings.py
app.config_from_object("django.conf:settings", namespace="CELERY")
# Auto-discover tasks.py in installed apps
app.autodiscover_tasks()
