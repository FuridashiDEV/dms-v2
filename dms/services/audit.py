from __future__ import annotations

import hashlib
from typing import Any

from django.contrib.auth import get_user_model

from dms.models import AuditEvent
from dms.services.data_governance import sanitize_governance_metadata


def get_client_ip(request) -> str | None:
    if request is None:
        return None

    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def get_user_agent(request) -> str:
    if request is None:
        return ""
    return (request.META.get("HTTP_USER_AGENT") or "")[:1000]


def _is_authenticated_user(user) -> bool:
    return bool(user and getattr(user, "is_authenticated", False))


def _metadata_for_document(document) -> dict[str, Any]:
    if document is None:
        return {}
    title_hash = hashlib.sha256((document.title or "").encode("utf-8")).hexdigest() if document.title else ""
    return {
        "document_id": document.id,
        "document_status": document.status,
        "document_public_id": str(document.public_id) if document.public_id else "",
        "checksum_sha256": document.checksum_sha256,
        "document_title_hash": title_hash,
    }


def record_audit_event(
    *,
    event_type: str,
    request=None,
    user=None,
    document=None,
    document_version=None,
    organization=None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    if user is None and request is not None:
        user = getattr(request, "user", None)
    if not _is_authenticated_user(user):
        user = None

    if document is None and document_version is not None:
        document = document_version.document

    if organization is None:
        if document is not None:
            organization = document.organization
        elif document_version is not None:
            organization = document_version.organization
        elif user is not None:
            User = get_user_model()
            if isinstance(user, User) and user.department_id:
                organization = user.department.organization

    event_metadata = _metadata_for_document(document)
    if document_version is not None:
        event_metadata.update(
            {
                "document_version_id": document_version.id,
                "document_version_number": document_version.number,
                "document_version_checksum_sha256": document_version.checksum_sha256,
            }
        )
    if metadata:
        event_metadata.update(metadata)
    event_metadata = sanitize_governance_metadata(event_metadata)

    return AuditEvent.objects.create(
        organization=organization,
        user=user,
        document=document,
        document_version=document_version,
        event_type=event_type,
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
        metadata=event_metadata,
    )
