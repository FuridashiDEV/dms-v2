from __future__ import annotations

from django.conf import settings
from django.db import connections
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health_check(request):
    checks = {}
    status_code = 200

    if getattr(settings, "HEALTH_CHECK_DATABASE", True):
        try:
            connections["default"].ensure_connection()
            checks["database"] = "ok"
        except OperationalError:
            checks["database"] = "error"
            status_code = 503

    if getattr(settings, "HEALTH_CHECK_QDRANT", False):
        try:
            from dms.services.vector_store import ensure_collection

            checks["qdrant"] = "ok" if ensure_collection() else "error"
            if checks["qdrant"] != "ok":
                status_code = 503
        except Exception:
            checks["qdrant"] = "error"
            status_code = 503

    if not checks:
        checks["application"] = "ok"

    return JsonResponse(
        {
            "status": "ok" if status_code == 200 else "error",
            "checks": checks,
        },
        status=status_code,
    )
