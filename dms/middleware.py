from __future__ import annotations

from django.http import HttpResponseForbidden

from dms.services.audit import get_client_ip, record_audit_event
from dms.services.enterprise_security import is_request_ip_allowed_for_user
from dms.utils import get_user_organizations


class OrganizationIPAllowlistMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info or ""
        if path.startswith(("/login/", "/logout/", "/health/", "/portal/")):
            return self.get_response(request)

        user = getattr(request, "user", None)
        if getattr(user, "is_authenticated", False) and not is_request_ip_allowed_for_user(request):
            organization = get_user_organizations(user).first()
            record_audit_event(
                event_type="SECURITY_IP_ALLOWLIST_DENIED",
                request=request,
                user=user,
                organization=organization,
                metadata={
                    "path": path[:250],
                    "client_ip": get_client_ip(request),
                    "control": "organization_ip_allowlist",
                },
            )
            return HttpResponseForbidden("Access denied by organization IP allowlist.")

        return self.get_response(request)
