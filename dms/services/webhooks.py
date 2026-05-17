from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from dms.models import WebhookDelivery, WebhookEndpoint
from dms.services.usage import SENSITIVE_KEY_PARTS, hash_webhook_secret


logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 5
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BASE_SECONDS = 60
MAX_ERROR_LENGTH = 2000


@dataclass
class WebhookHttpResponse:
    status_code: int
    body: str = ""


WebhookTransport = Callable[[str, bytes, dict[str, str], int], WebhookHttpResponse]
SecretResolver = Callable[[WebhookEndpoint], str]


def sanitize_webhook_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        safe = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
                continue
            safe[str(key)] = sanitize_webhook_payload(item)
        return safe
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_webhook_payload(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return "[bytes]"
    return value


def redact_secret_text(value: str, *, extra_secrets: Sequence[str] | None = None) -> str:
    redacted = str(value or "")
    for secret in extra_secrets or []:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    redacted = re.sub(
        r"(?i)(token|secret|password|api[_-]?key|authorization)\s*[:=]\s*[^,\s;]+",
        r"\1=[redacted]",
        redacted,
    )
    return redacted[:MAX_ERROR_LENGTH]


def _json_body(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        sanitize_webhook_payload(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _configured_secret(endpoint: WebhookEndpoint) -> str:
    configured = getattr(settings, "DMS_WEBHOOK_SIGNING_SECRETS", {}) or {}
    for key in (str(endpoint.id), endpoint.name):
        secret = configured.get(key)
        if secret:
            return str(secret)

    env_key = "DMS_WEBHOOK_SECRET_" + re.sub(r"[^A-Z0-9]+", "_", endpoint.name.upper()).strip("_")
    return os.environ.get(f"DMS_WEBHOOK_SECRET_{endpoint.id}") or os.environ.get(env_key, "")


def resolve_webhook_signing_secret(endpoint: WebhookEndpoint) -> str:
    secret = _configured_secret(endpoint)
    if not secret:
        return ""
    if endpoint.secret_hash and hash_webhook_secret(secret) != endpoint.secret_hash:
        logger.warning("Configured webhook signing secret does not match endpoint hash", extra={"endpoint_id": endpoint.id})
        return ""
    return secret


def build_webhook_headers(
    *,
    delivery: WebhookDelivery,
    body: bytes,
    timestamp: str,
    signing_secret: str = "",
) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "UniDMS-Webhook/1.0",
        "X-DMS-Event": delivery.event_type,
        "X-DMS-Delivery-ID": str(delivery.id),
        "X-DMS-Timestamp": timestamp,
    }
    if signing_secret:
        signed_payload = timestamp.encode("utf-8") + b"." + body
        digest = hmac.new(signing_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        headers["X-DMS-Signature"] = f"sha256={digest}"
    return headers


def default_webhook_transport(url: str, body: bytes, headers: dict[str, str], timeout: int) -> WebhookHttpResponse:
    request = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read(2048).decode("utf-8", errors="replace")
            return WebhookHttpResponse(status_code=int(response.status), body=response_body)
    except urllib.error.HTTPError as exc:
        response_body = exc.read(2048).decode("utf-8", errors="replace")
        return WebhookHttpResponse(status_code=int(exc.code), body=response_body)


def _retry_delay_seconds(attempt_count: int) -> int:
    base = int(getattr(settings, "DMS_WEBHOOK_RETRY_BASE_SECONDS", DEFAULT_RETRY_BASE_SECONDS))
    delay = base * (2 ** max(attempt_count - 1, 0))
    return min(delay, 60 * 60)


def _max_attempts(value: int | None = None) -> int:
    configured = value if value is not None else getattr(settings, "DMS_WEBHOOK_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)
    return max(int(configured or DEFAULT_MAX_ATTEMPTS), 1)


def _timeout_seconds(value: int | None = None) -> int:
    configured = value if value is not None else getattr(settings, "DMS_WEBHOOK_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
    return max(int(configured or DEFAULT_TIMEOUT_SECONDS), 1)


def _mark_failure(
    *,
    delivery: WebhookDelivery,
    error_message: str,
    response_status: int | None,
    max_attempts: int,
    signing_secret: str = "",
) -> WebhookDelivery:
    delivery.response_status = response_status
    delivery.last_error = redact_secret_text(error_message, extra_secrets=[signing_secret])
    if delivery.attempt_count >= max_attempts:
        delivery.status = WebhookDelivery.Status.FAILED
        delivery.next_attempt_at = None
    else:
        delivery.status = WebhookDelivery.Status.PENDING
        delivery.next_attempt_at = timezone.now() + timezone.timedelta(seconds=_retry_delay_seconds(delivery.attempt_count))
    delivery.save(update_fields=["status", "attempt_count", "next_attempt_at", "response_status", "last_error", "payload", "updated_at"])
    return delivery


@transaction.atomic
def send_webhook_delivery(
    delivery: WebhookDelivery,
    *,
    transport: WebhookTransport = default_webhook_transport,
    secret_resolver: SecretResolver = resolve_webhook_signing_secret,
    timeout_seconds: int | None = None,
    max_attempts: int | None = None,
) -> WebhookDelivery:
    delivery = (
        WebhookDelivery.objects
        .select_for_update()
        .select_related("endpoint", "organization")
        .get(pk=delivery.pk)
    )

    if delivery.status == WebhookDelivery.Status.CANCELED:
        return delivery
    if not delivery.endpoint.is_active:
        delivery.status = WebhookDelivery.Status.CANCELED
        delivery.last_error = "Webhook endpoint is inactive."
        delivery.next_attempt_at = None
        delivery.save(update_fields=["status", "last_error", "next_attempt_at", "updated_at"])
        return delivery

    safe_payload = sanitize_webhook_payload(delivery.payload or {})
    if safe_payload != delivery.payload:
        delivery.payload = safe_payload

    delivery.attempt_count += 1
    body = _json_body(safe_payload)
    timestamp = str(int(timezone.now().timestamp()))
    signing_secret = secret_resolver(delivery.endpoint)
    headers = build_webhook_headers(
        delivery=delivery,
        body=body,
        timestamp=timestamp,
        signing_secret=signing_secret,
    )

    try:
        response = transport(delivery.endpoint.url, body, headers, _timeout_seconds(timeout_seconds))
    except Exception as exc:
        logger.warning("Webhook delivery transport failed", extra={"delivery_id": delivery.id, "endpoint_id": delivery.endpoint_id})
        return _mark_failure(
            delivery=delivery,
            error_message=str(exc),
            response_status=None,
            max_attempts=_max_attempts(max_attempts),
            signing_secret=signing_secret,
        )

    if 200 <= response.status_code < 300:
        delivery.status = WebhookDelivery.Status.SENT
        delivery.response_status = response.status_code
        delivery.last_error = ""
        delivery.next_attempt_at = None
        delivery.save(update_fields=["status", "attempt_count", "next_attempt_at", "response_status", "last_error", "payload", "updated_at"])
        return delivery

    return _mark_failure(
        delivery=delivery,
        error_message=f"HTTP {response.status_code}",
        response_status=response.status_code,
        max_attempts=_max_attempts(max_attempts),
        signing_secret=signing_secret,
    )


def send_due_webhook_deliveries(
    *,
    limit: int = 100,
    transport: WebhookTransport = default_webhook_transport,
    secret_resolver: SecretResolver = resolve_webhook_signing_secret,
    timeout_seconds: int | None = None,
    max_attempts: int | None = None,
) -> list[WebhookDelivery]:
    now = timezone.now()
    deliveries = (
        WebhookDelivery.objects
        .filter(status=WebhookDelivery.Status.PENDING)
        .filter(next_attempt_at__lte=now)
        .select_related("endpoint", "organization")
        .order_by("next_attempt_at", "id")[: max(int(limit or 100), 1)]
    )
    sent: list[WebhookDelivery] = []
    for delivery in deliveries:
        sent.append(
            send_webhook_delivery(
                delivery,
                transport=transport,
                secret_resolver=secret_resolver,
                timeout_seconds=timeout_seconds,
                max_attempts=max_attempts,
            )
        )
    return sent


def retry_webhook_delivery(
    delivery: WebhookDelivery,
    *,
    transport: WebhookTransport = default_webhook_transport,
    secret_resolver: SecretResolver = resolve_webhook_signing_secret,
    timeout_seconds: int | None = None,
    max_attempts: int | None = None,
) -> WebhookDelivery:
    delivery.status = WebhookDelivery.Status.PENDING
    delivery.next_attempt_at = timezone.now()
    delivery.response_status = None
    delivery.last_error = ""
    delivery.save(update_fields=["status", "next_attempt_at", "response_status", "last_error", "updated_at"])
    return send_webhook_delivery(
        delivery,
        transport=transport,
        secret_resolver=secret_resolver,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )
