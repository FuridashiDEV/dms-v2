from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health_check(request):
    from dms.services.disaster_recovery import build_health_checks

    checks, status_code = build_health_checks()

    return JsonResponse(
        {
            "status": "ok" if status_code == 200 else "error",
            "checks": checks,
        },
        status=status_code,
    )
