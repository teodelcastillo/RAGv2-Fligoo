from django.db import connections
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.utils import timezone


import logging

logger = logging.getLogger(__name__)


def health_check(request):
    db_ok = True
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1;")
            cursor.fetchone()
    except Exception as exc:
        logger.error("Health check DB failed: %s", exc)
        db_ok = False

    status_code = 200 if db_ok else 503
    return JsonResponse(
        {
            "status": "ok" if db_ok else "degraded",
            "service": "ragv2-fligoo-api",
            "database": "up" if db_ok else "down",
            "timestamp": timezone.now().isoformat(),
        },
        status=status_code,
    )
