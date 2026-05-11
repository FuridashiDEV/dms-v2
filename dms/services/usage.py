from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from django.utils import timezone

from dms.models import Document, Organization, UsageEvent, WebhookDelivery, WebhookEndpoint


logger = logging.getLogger(__name__)

SENSITIVE_KEY_PARTS = ("token", "secret", "api_key", "apikey", "password", "private_key", "authorization")


def hash_webhook_secret(secret: str) -> str:
    return hashlib.sha256((secret or "").encode("utf-8")).hexdigest()


def _is_authenticated_user(user) -> bool:
    return bool(user and getattr(user, "is_authenticated", False))


def _safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        safe = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
                continue
            safe[str(key)] = _safe_value(item)
        return safe
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_safe_value(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    return value


def _resolve_organization(*, organization=None, document: Document | None = None, user=None):
    if organization is not None:
        return organization
    if document is not None:
        return document.organization
    if _is_authenticated_user(user) and getattr(user, "department_id", None):
        return user.department.organization
    return None


def _delivery_payload(usage_event: UsageEvent) -> dict[str, Any]:
    return {
        "id": usage_event.id,
        "type": usage_event.event_type,
        "created_at": usage_event.created_at.isoformat(),
        "organization": {
            "id": usage_event.organization_id,
            "name": usage_event.organization.name,
        },
        "document_id": usage_event.document_id,
        "user_id": usage_event.user_id,
        "source": usage_event.source,
        "quantity": usage_event.quantity,
        "metadata": _safe_value(usage_event.metadata),
    }


def queue_webhook_deliveries_for_usage_event(usage_event: UsageEvent) -> list[WebhookDelivery]:
    endpoints = WebhookEndpoint.objects.filter(
        organization=usage_event.organization,
        is_active=True,
    ).order_by("id")
    payload = _delivery_payload(usage_event)
    deliveries: list[WebhookDelivery] = []
    for endpoint in endpoints:
        if not endpoint.accepts_event(usage_event.event_type):
            continue
        deliveries.append(
            WebhookDelivery(
                organization=usage_event.organization,
                endpoint=endpoint,
                usage_event=usage_event,
                event_type=usage_event.event_type,
                payload=payload,
                status=WebhookDelivery.Status.PENDING,
                next_attempt_at=timezone.now(),
            )
        )
    if deliveries:
        return WebhookDelivery.objects.bulk_create(deliveries)
    return []


def record_usage_event(
    *,
    event_type: str,
    organization: Organization | None = None,
    user=None,
    document: Document | None = None,
    source: str = "",
    quantity: int = 1,
    metadata: dict[str, Any] | None = None,
) -> UsageEvent | None:
    organization = _resolve_organization(organization=organization, document=document, user=user)
    if organization is None:
        return None
    try:
        usage_event = UsageEvent.objects.create(
            organization=organization,
            user=user if _is_authenticated_user(user) else None,
            document=document,
            event_type=event_type,
            source=(source or "")[:80],
            quantity=max(int(quantity or 1), 1),
            metadata=_safe_value(metadata or {}),
        )
        queue_webhook_deliveries_for_usage_event(usage_event)
        return usage_event
    except Exception:
        logger.exception("Could not record usage event")
        return None
