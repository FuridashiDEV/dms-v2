from __future__ import annotations

import csv
import io
import ipaddress
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone

from dms.models import AuditEvent, Organization
from dms.services.audit import get_client_ip
from dms.utils import get_user_organizations


SECURITY_EVENT_TYPES = {
    "SECURITY_LOGIN_SUCCESS",
    "SECURITY_LOGIN_FAILURE",
    "SECURITY_LOGIN_RATE_LIMITED",
    "SECURITY_IP_ALLOWLIST_DENIED",
    "SECURITY_AUDIT_EXPORTED",
    AuditEvent.EventType.DOCUMENT_ACCESS_GRANTED,
    AuditEvent.EventType.DOCUMENT_ACCESS_REVOKED,
    AuditEvent.EventType.DOCUMENT_DOWNLOADED,
    AuditEvent.EventType.DOCUMENT_VERSION_DOWNLOADED,
    AuditEvent.EventType.EXCHANGE_OPENED,
    AuditEvent.EventType.EXCHANGE_DOWNLOADED,
    AuditEvent.EventType.EXCHANGE_REVOKED,
}

SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "private_key",
    "access_key",
    "authorization",
    "cookie",
    "session",
)


@dataclass(frozen=True)
class SecurityFinding:
    level: str
    code: str
    message: str


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str) and len(value) > 160:
        return value[:157] + "..."
    return value


def get_security_organizations(user):
    if getattr(user, "is_superuser", False):
        return Organization.objects.filter(is_active=True).order_by("name", "id")
    return get_user_organizations(user).order_by("name", "id")


def user_can_view_security(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return bool(getattr(user, "is_superuser", False) or getattr(user, "role", "") == "ADMIN")


def get_selected_security_organization(user, organization_id: str | None):
    organizations = get_security_organizations(user)
    if organization_id:
        return organizations.filter(id=organization_id).first()
    return organizations.first()


def get_security_events(*, user, organization=None, limit: int = 100):
    organizations = get_security_organizations(user)
    events = (
        AuditEvent.objects
        .filter(organization__in=organizations)
        .select_related("organization", "user", "document", "document_version")
        .order_by("-created_at", "-id")
    )
    if organization is not None:
        events = events.filter(organization=organization)

    events = events.filter(event_type__in=SECURITY_EVENT_TYPES)[:limit]
    return [
        {
            "event": event,
            "metadata": redact_sensitive(event.metadata),
        }
        for event in events
    ]


def build_security_summary(*, user, organization=None) -> dict[str, int]:
    organizations = get_security_organizations(user)
    events = AuditEvent.objects.filter(organization__in=organizations)
    if organization is not None:
        events = events.filter(organization=organization)

    now = timezone.now()
    day_start = now - timedelta(days=1)
    week_start = now - timedelta(days=7)
    return {
        "security_events_24h": events.filter(event_type__in=SECURITY_EVENT_TYPES, created_at__gte=day_start).count(),
        "security_events_7d": events.filter(event_type__in=SECURITY_EVENT_TYPES, created_at__gte=week_start).count(),
        "downloads_7d": events.filter(
            event_type__in=[
                AuditEvent.EventType.DOCUMENT_DOWNLOADED,
                AuditEvent.EventType.DOCUMENT_VERSION_DOWNLOADED,
                AuditEvent.EventType.EXCHANGE_DOWNLOADED,
            ],
            created_at__gte=week_start,
        ).count(),
        "access_changes_7d": events.filter(
            event_type__in=[
                AuditEvent.EventType.DOCUMENT_ACCESS_GRANTED,
                AuditEvent.EventType.DOCUMENT_ACCESS_REVOKED,
            ],
            created_at__gte=week_start,
        ).count(),
        "login_failures_7d": events.filter(
            event_type__in=["SECURITY_LOGIN_FAILURE", "SECURITY_LOGIN_RATE_LIMITED"],
            created_at__gte=week_start,
        ).count(),
    }


def build_audit_export_response(*, user, organization=None) -> HttpResponse:
    organizations = get_security_organizations(user)
    events = (
        AuditEvent.objects
        .filter(organization__in=organizations)
        .select_related("organization", "user", "document", "document_version")
        .order_by("-created_at", "-id")
    )
    if organization is not None:
        events = events.filter(organization=organization)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "created_at",
            "organization",
            "event_type",
            "user",
            "document_id",
            "document_title",
            "ip_address",
            "user_agent",
            "metadata",
        ]
    )
    for event in events[:5000]:
        writer.writerow(
            [
                event.created_at.isoformat(),
                event.organization.name if event.organization else "",
                event.event_type,
                event.user.username if event.user else "",
                event.document_id or "",
                event.document.title if event.document else "",
                event.ip_address or "",
                (event.user_agent or "")[:250],
                json.dumps(redact_sensitive(event.metadata), ensure_ascii=False, sort_keys=True),
            ]
        )

    response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="audit-events.csv"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _configured_allowlists() -> dict[str, list[str]]:
    configured = getattr(settings, "DMS_ORGANIZATION_IP_ALLOWLISTS", {}) or {}
    if not isinstance(configured, dict):
        return {}
    return {
        str(key): [str(item).strip() for item in value if str(item).strip()]
        for key, value in configured.items()
        if isinstance(value, (list, tuple, set))
    }


def organization_ip_allowlist(organization: Organization) -> list[str]:
    configured = _configured_allowlists()
    return configured.get(str(organization.id), []) or configured.get(organization.slug, [])


def is_ip_allowed_for_organization(ip_address: str | None, organization: Organization) -> bool:
    allowlist = organization_ip_allowlist(organization)
    if not allowlist:
        return True
    if not ip_address:
        return False
    try:
        client_ip = ipaddress.ip_address(ip_address)
    except ValueError:
        return False
    for item in allowlist:
        try:
            if client_ip in ipaddress.ip_network(item, strict=False):
                return True
        except ValueError:
            continue
    return False


def is_request_ip_allowed_for_user(request) -> bool:
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return True
    if getattr(user, "is_superuser", False):
        return True

    organizations = list(get_user_organizations(user))
    allowlisted_organizations = [org for org in organizations if organization_ip_allowlist(org)]
    if not allowlisted_organizations:
        return True

    ip_address = get_client_ip(request)
    return any(is_ip_allowed_for_organization(ip_address, organization) for organization in allowlisted_organizations)


def validate_production_security_settings() -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []

    if settings.DEBUG:
        findings.append(SecurityFinding("error", "debug_enabled", "DEBUG must be disabled in production."))

    if not getattr(settings, "SECRET_KEY", "") or settings.SECRET_KEY == "django-insecure-local-dev-only":
        findings.append(SecurityFinding("error", "weak_secret_key", "DJANGO_SECRET_KEY must be set to a production value."))

    allowed_hosts = set(getattr(settings, "ALLOWED_HOSTS", []))
    if not allowed_hosts or "*" in allowed_hosts:
        findings.append(SecurityFinding("error", "allowed_hosts", "DJANGO_ALLOWED_HOSTS must be explicit."))

    if not settings.SESSION_COOKIE_SECURE:
        findings.append(SecurityFinding("warning", "session_cookie_secure", "SESSION_COOKIE_SECURE should be enabled behind HTTPS."))
    if not settings.CSRF_COOKIE_SECURE:
        findings.append(SecurityFinding("warning", "csrf_cookie_secure", "CSRF_COOKIE_SECURE should be enabled behind HTTPS."))
    if not settings.SECURE_SSL_REDIRECT:
        findings.append(SecurityFinding("warning", "ssl_redirect", "SECURE_SSL_REDIRECT is disabled."))
    if not settings.SECURE_HSTS_SECONDS:
        findings.append(SecurityFinding("warning", "hsts", "HSTS is disabled."))
    if settings.SESSION_COOKIE_AGE > 8 * 60 * 60:
        findings.append(SecurityFinding("warning", "session_age", "Session age is longer than 8 hours."))
    if not settings.AUTH_PASSWORD_VALIDATORS:
        findings.append(SecurityFinding("warning", "password_validators", "Password validators are disabled."))

    return findings
