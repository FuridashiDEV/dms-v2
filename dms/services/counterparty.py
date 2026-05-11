from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from dms.models import (
    AuditEvent,
    Counterparty,
    Document,
    DocumentExchange,
    ExchangeEvent,
    Folder,
)
from dms.services.audit import get_client_ip, get_user_agent, record_audit_event
from dms.services.document_creation import create_document_from_uploaded_file
from dms.utils import get_allowed_departments, user_can_access_document


TOKEN_BYTES = 32


class ExchangeError(ValueError):
    pass


class ExchangePermissionError(PermissionError):
    pass


@dataclass(frozen=True)
class CreatedExchange:
    exchange: DocumentExchange
    token: str

    def portal_path(self) -> str:
        return reverse("dms:counterparty_portal", args=[self.token])


def generate_exchange_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_exchange_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def can_send_document_exchange(user, document: Document) -> bool:
    if not user_can_access_document(user, document):
        return False
    if user.role == "ADMIN":
        return True
    if document.uploaded_by_id == user.id:
        return True
    if not getattr(user, "department_id", None):
        return False
    return get_allowed_departments(user).filter(id=document.department_id).exists()


def _build_portal_url(request, token: str) -> str:
    path = reverse("dms:counterparty_portal", args=[token])
    if request is None:
        return path
    return request.build_absolute_uri(path)


def _audit_event_type(event_type: str) -> str | None:
    return {
        ExchangeEvent.EventType.SENT: AuditEvent.EventType.EXCHANGE_SENT,
        ExchangeEvent.EventType.OPENED: AuditEvent.EventType.EXCHANGE_OPENED,
        ExchangeEvent.EventType.DOWNLOADED: AuditEvent.EventType.EXCHANGE_DOWNLOADED,
        ExchangeEvent.EventType.RECEIVED: AuditEvent.EventType.EXCHANGE_RECEIVED,
        ExchangeEvent.EventType.ACCEPTED: AuditEvent.EventType.EXCHANGE_ACCEPTED,
        ExchangeEvent.EventType.REJECTED: AuditEvent.EventType.EXCHANGE_REJECTED,
        ExchangeEvent.EventType.COMMENTED: AuditEvent.EventType.EXCHANGE_COMMENTED,
    }.get(event_type)


def record_exchange_event(
    *,
    exchange: DocumentExchange,
    event_type: str,
    request=None,
    user=None,
    actor_name: str = "",
    actor_email: str = "",
    comment: str = "",
    metadata: dict | None = None,
) -> ExchangeEvent:
    event = ExchangeEvent.objects.create(
        organization=exchange.organization,
        exchange=exchange,
        document=exchange.document,
        event_type=event_type,
        actor_name=actor_name[:255],
        actor_email=actor_email[:254],
        comment=comment or "",
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
    )

    audit_type = _audit_event_type(event_type)
    if audit_type:
        audit_metadata = {
            "document_exchange_id": exchange.id,
            "counterparty_id": exchange.counterparty_id,
            "counterparty_name": exchange.counterparty.name,
            "exchange_event_id": event.id,
            "exchange_event_type": event.event_type,
            "exchange_status": exchange.status,
        }
        if metadata:
            audit_metadata.update(metadata)
        record_audit_event(
            event_type=audit_type,
            request=request,
            user=user,
            document=exchange.document,
            organization=exchange.organization,
            metadata=audit_metadata,
        )
    return event


@transaction.atomic
def create_document_exchange(
    *,
    document: Document,
    counterparty: Counterparty,
    user,
    request=None,
    message: str = "",
    expires_at=None,
    business_document_type: str = "",
) -> CreatedExchange:
    document = Document.objects.select_for_update().get(pk=document.pk)
    counterparty = Counterparty.objects.get(pk=counterparty.pk)

    if counterparty.organization_id != document.organization_id:
        raise ExchangeError("Counterparty belongs to another organization.")
    if not counterparty.is_active:
        raise ExchangeError("Counterparty is inactive.")
    if not can_send_document_exchange(user, document):
        raise ExchangePermissionError("User cannot send this document to counterparty.")

    token = generate_exchange_token()
    token_hash = hash_exchange_token(token)
    while DocumentExchange.objects.filter(token_hash=token_hash).exists():
        token = generate_exchange_token()
        token_hash = hash_exchange_token(token)

    exchange = DocumentExchange.objects.create(
        organization=document.organization,
        document=document,
        counterparty=counterparty,
        sent_by=user,
        status=DocumentExchange.Status.SENT,
        direction=DocumentExchange.Direction.OUTGOING,
        business_document_type=business_document_type or "",
        token_hash=token_hash,
        token_hint=token[-8:],
        message=message or "",
        expires_at=expires_at,
    )
    record_exchange_event(
        exchange=exchange,
        event_type=ExchangeEvent.EventType.SENT,
        request=request,
        user=user,
        actor_name=getattr(user, "get_full_name", lambda: "")() or getattr(user, "username", ""),
        actor_email=getattr(user, "email", ""),
        comment=message,
        metadata={"portal_url": _build_portal_url(request, token)},
    )
    return CreatedExchange(exchange=exchange, token=token)


@transaction.atomic
def create_incoming_document_exchange(
    *,
    uploaded_file,
    department,
    counterparty: Counterparty,
    user,
    folder: Folder | None = None,
    title: str = "",
    description: str = "",
    business_document_type: str = "",
    message: str = "",
    request=None,
    indexer=None,
) -> tuple[DocumentExchange, Document]:
    counterparty = Counterparty.objects.get(pk=counterparty.pk)
    if counterparty.organization_id != department.organization_id:
        raise ExchangeError("Counterparty belongs to another organization.")
    if not counterparty.is_active:
        raise ExchangeError("Counterparty is inactive.")
    if not get_allowed_departments(user).filter(id=department.id).exists():
        raise ExchangePermissionError("User cannot receive documents for this department.")
    if folder is not None and folder.department_id != department.id:
        raise ExchangeError("Folder belongs to another department.")

    document, version = create_document_from_uploaded_file(
        uploaded_file=uploaded_file,
        department=department,
        folder=folder,
        title=title,
        description=description,
        source_system="b2b_incoming_exchange",
        uploaded_by=user,
        request=request,
        run_ai=False,
        indexer=indexer or (lambda document: False),
        audit_metadata={
            "b2b_direction": DocumentExchange.Direction.INCOMING,
            "counterparty_id": counterparty.id,
            "counterparty_name": counterparty.name,
        },
    )

    token = generate_exchange_token()
    token_hash = hash_exchange_token(token)
    while DocumentExchange.objects.filter(token_hash=token_hash).exists():
        token = generate_exchange_token()
        token_hash = hash_exchange_token(token)

    exchange = DocumentExchange.objects.create(
        organization=document.organization,
        document=document,
        counterparty=counterparty,
        received_by=user,
        direction=DocumentExchange.Direction.INCOMING,
        status=DocumentExchange.Status.RECEIVED,
        business_document_type=business_document_type or "",
        token_hash=token_hash,
        token_hint=token[-8:],
        message=message or "",
        received_at=timezone.now(),
    )
    record_exchange_event(
        exchange=exchange,
        event_type=ExchangeEvent.EventType.RECEIVED,
        request=request,
        user=user,
        actor_name=getattr(user, "get_full_name", lambda: "")() or getattr(user, "username", ""),
        actor_email=getattr(user, "email", ""),
        comment=message,
        metadata={
            "document_version_id": version.id,
            "document_version_number": version.number,
        },
    )
    return exchange, document


def resolve_exchange_token(token: str) -> DocumentExchange | None:
    token_hash = hash_exchange_token(token or "")
    return (
        DocumentExchange.objects
        .select_related("organization", "document", "document__department", "counterparty", "sent_by")
        .filter(token_hash=token_hash)
        .first()
    )


def is_exchange_expired(exchange: DocumentExchange) -> bool:
    return bool(exchange.expires_at and exchange.expires_at <= timezone.now())


@transaction.atomic
def mark_exchange_opened(*, exchange: DocumentExchange, request=None) -> DocumentExchange:
    exchange = DocumentExchange.objects.select_for_update().get(pk=exchange.pk)
    if exchange.status == DocumentExchange.Status.SENT:
        exchange.status = DocumentExchange.Status.OPENED
        exchange.opened_at = timezone.now()
        exchange.save(update_fields=["status", "opened_at", "updated_at"])
        record_exchange_event(
            exchange=exchange,
            event_type=ExchangeEvent.EventType.OPENED,
            request=request,
            actor_name=exchange.counterparty.contact_name or exchange.counterparty.name,
            actor_email=exchange.counterparty.email,
        )
    return exchange


@transaction.atomic
def expire_exchange(*, exchange: DocumentExchange, request=None) -> DocumentExchange:
    exchange = DocumentExchange.objects.select_for_update().get(pk=exchange.pk)
    if exchange.status not in {
        DocumentExchange.Status.ACCEPTED,
        DocumentExchange.Status.REJECTED,
        DocumentExchange.Status.EXPIRED,
        DocumentExchange.Status.REVOKED,
    }:
        exchange.status = DocumentExchange.Status.EXPIRED
        exchange.save(update_fields=["status", "updated_at"])
        record_exchange_event(
            exchange=exchange,
            event_type=ExchangeEvent.EventType.EXPIRED,
            request=request,
            actor_name=exchange.counterparty.contact_name or exchange.counterparty.name,
            actor_email=exchange.counterparty.email,
        )
    return exchange


@transaction.atomic
def record_exchange_download(*, exchange: DocumentExchange, request=None) -> ExchangeEvent:
    exchange = DocumentExchange.objects.select_for_update().get(pk=exchange.pk)
    return record_exchange_event(
        exchange=exchange,
        event_type=ExchangeEvent.EventType.DOWNLOADED,
        request=request,
        actor_name=exchange.counterparty.contact_name or exchange.counterparty.name,
        actor_email=exchange.counterparty.email,
    )


@transaction.atomic
def accept_exchange(*, exchange: DocumentExchange, request=None, comment: str = "") -> DocumentExchange:
    exchange = DocumentExchange.objects.select_for_update().get(pk=exchange.pk)
    if exchange.is_terminal:
        raise ExchangeError("Exchange is already closed.")
    exchange.status = DocumentExchange.Status.ACCEPTED
    exchange.responded_at = timezone.now()
    exchange.save(update_fields=["status", "responded_at", "updated_at"])
    record_exchange_event(
        exchange=exchange,
        event_type=ExchangeEvent.EventType.ACCEPTED,
        request=request,
        actor_name=exchange.counterparty.contact_name or exchange.counterparty.name,
        actor_email=exchange.counterparty.email,
        comment=comment,
    )
    return exchange


@transaction.atomic
def reject_exchange(*, exchange: DocumentExchange, request=None, comment: str = "") -> DocumentExchange:
    exchange = DocumentExchange.objects.select_for_update().get(pk=exchange.pk)
    if exchange.is_terminal:
        raise ExchangeError("Exchange is already closed.")
    exchange.status = DocumentExchange.Status.REJECTED
    exchange.responded_at = timezone.now()
    exchange.save(update_fields=["status", "responded_at", "updated_at"])
    record_exchange_event(
        exchange=exchange,
        event_type=ExchangeEvent.EventType.REJECTED,
        request=request,
        actor_name=exchange.counterparty.contact_name or exchange.counterparty.name,
        actor_email=exchange.counterparty.email,
        comment=comment,
    )
    return exchange


@transaction.atomic
def comment_exchange(*, exchange: DocumentExchange, request=None, comment: str) -> ExchangeEvent:
    exchange = DocumentExchange.objects.select_for_update().get(pk=exchange.pk)
    if exchange.is_terminal:
        raise ExchangeError("Exchange is already closed.")
    if not comment:
        raise ExchangeError("Comment is required.")
    return record_exchange_event(
        exchange=exchange,
        event_type=ExchangeEvent.EventType.COMMENTED,
        request=request,
        actor_name=exchange.counterparty.contact_name or exchange.counterparty.name,
        actor_email=exchange.counterparty.email,
        comment=comment,
    )
