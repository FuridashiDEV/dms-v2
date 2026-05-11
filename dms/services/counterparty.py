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
    CounterpartyContact,
    Document,
    DocumentExchange,
    ExchangeEvent,
    ExchangeMessage,
    Folder,
    UsageEvent,
)
from dms.services.audit import get_client_ip, get_user_agent, record_audit_event
from dms.services.document_creation import create_document_from_uploaded_file
from dms.services.usage import record_usage_event
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


def can_access_document_exchange(user, exchange: DocumentExchange) -> bool:
    return user_can_access_document(user, exchange.document)


def _actor_display_name(user) -> str:
    return getattr(user, "get_full_name", lambda: "")() or getattr(user, "username", "")


def ensure_counterparty_contact(
    *,
    counterparty: Counterparty,
    contact: CounterpartyContact | None = None,
    name: str = "",
    email: str = "",
    user=None,
) -> CounterpartyContact | None:
    if contact is not None:
        contact = CounterpartyContact.objects.select_related("counterparty").get(pk=contact.pk)
        if contact.counterparty_id != counterparty.id:
            raise ExchangeError("Counterparty contact belongs to another counterparty.")
        if not contact.is_active:
            raise ExchangeError("Counterparty contact is inactive.")
        return contact

    name = (name or "").strip()
    email = (email or "").strip()
    if not name and not email:
        return None

    existing = None
    if email:
        existing = CounterpartyContact.objects.filter(
            counterparty=counterparty,
            email__iexact=email,
        ).first()
    if existing is None and name:
        existing = CounterpartyContact.objects.filter(
            counterparty=counterparty,
            name__iexact=name,
            email="",
        ).first()
    if existing is not None:
        updates = []
        if name and existing.name != name:
            existing.name = name
            updates.append("name")
        if email and not existing.email:
            existing.email = email
            updates.append("email")
        if not existing.is_active:
            existing.is_active = True
            updates.append("is_active")
        if updates:
            existing.save(update_fields=[*updates, "updated_at"])
        return existing

    return CounterpartyContact.objects.create(
        counterparty=counterparty,
        name=name or email or counterparty.name,
        email=email,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


def _portal_metadata(request) -> dict:
    path = reverse("dms:counterparty_portal", args=["[redacted]"])
    if request is None:
        return {"portal_path": path}
    return {"portal_path": request.build_absolute_uri(path)}


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
            "counterparty_contact_id": exchange.counterparty_contact_id,
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
    record_usage_event(
        event_type=UsageEvent.EventType.EXCHANGE_EVENT,
        user=user,
        document=exchange.document,
        source="counterparty_exchange",
        metadata={
            "document_exchange_id": exchange.id,
            "exchange_event_id": event.id,
            "exchange_event_type": event.event_type,
            "exchange_direction": exchange.direction,
            "exchange_status": exchange.status,
            "counterparty_id": exchange.counterparty_id,
            "counterparty_contact_id": exchange.counterparty_contact_id,
        },
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
    counterparty_contact: CounterpartyContact | None = None,
    contact_name: str = "",
    contact_email: str = "",
) -> CreatedExchange:
    document = Document.objects.select_for_update().get(pk=document.pk)
    counterparty = Counterparty.objects.get(pk=counterparty.pk)

    if counterparty.organization_id != document.organization_id:
        raise ExchangeError("Counterparty belongs to another organization.")
    if not counterparty.is_active:
        raise ExchangeError("Counterparty is inactive.")
    if not can_send_document_exchange(user, document):
        raise ExchangePermissionError("User cannot send this document to counterparty.")
    counterparty_contact = ensure_counterparty_contact(
        counterparty=counterparty,
        contact=counterparty_contact,
        name=contact_name,
        email=contact_email,
        user=user,
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
        counterparty_contact=counterparty_contact,
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
        metadata=_portal_metadata(request),
    )
    if message:
        record_exchange_message(
            exchange=exchange,
            author_type=ExchangeMessage.AuthorType.INTERNAL,
            user=user,
            body=message,
            request=request,
            source_event_type=ExchangeEvent.EventType.SENT,
            create_comment_event=False,
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
    counterparty_contact: CounterpartyContact | None = None,
    contact_name: str = "",
    contact_email: str = "",
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
    counterparty_contact = ensure_counterparty_contact(
        counterparty=counterparty,
        contact=counterparty_contact,
        name=contact_name,
        email=contact_email,
        user=user,
    )

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
        counterparty_contact=counterparty_contact,
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
    if message:
        record_exchange_message(
            exchange=exchange,
            author_type=ExchangeMessage.AuthorType.EXTERNAL,
            counterparty_contact=counterparty_contact,
            body=message,
            request=request,
            source_event_type=ExchangeEvent.EventType.RECEIVED,
            create_comment_event=False,
        )
    return exchange, document


@transaction.atomic
def record_exchange_message(
    *,
    exchange: DocumentExchange,
    author_type: str,
    body: str,
    request=None,
    user=None,
    counterparty_contact: CounterpartyContact | None = None,
    source_event_type: str = "",
    create_comment_event: bool = True,
) -> ExchangeMessage:
    exchange = (
        DocumentExchange.objects
        .select_for_update()
        .select_related("organization", "document", "counterparty")
        .get(pk=exchange.pk)
    )
    body = (body or "").strip()
    if not body:
        raise ExchangeError("Message is required.")

    if author_type == ExchangeMessage.AuthorType.INTERNAL:
        if user is None or not can_access_document_exchange(user, exchange):
            raise ExchangePermissionError("User cannot message this exchange.")
        counterparty_contact = exchange.counterparty_contact
        actor_name = _actor_display_name(user)
        actor_email = getattr(user, "email", "")
    elif author_type == ExchangeMessage.AuthorType.EXTERNAL:
        if counterparty_contact is None:
            counterparty_contact = exchange.counterparty_contact
        if counterparty_contact is not None and counterparty_contact.counterparty_id != exchange.counterparty_id:
            raise ExchangeError("Counterparty contact belongs to another counterparty.")
        actor_name = (
            getattr(counterparty_contact, "name", "")
            or exchange.counterparty.contact_name
            or exchange.counterparty.name
        )
        actor_email = getattr(counterparty_contact, "email", "") or exchange.counterparty.email
    else:
        raise ExchangeError("Invalid message author type.")

    message = ExchangeMessage.objects.create(
        organization=exchange.organization,
        exchange=exchange,
        document=exchange.document,
        counterparty=exchange.counterparty,
        counterparty_contact=counterparty_contact,
        user=user if author_type == ExchangeMessage.AuthorType.INTERNAL else None,
        author_type=author_type,
        body=body,
        source_event_type=source_event_type or "",
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
    )

    if create_comment_event:
        record_exchange_event(
            exchange=exchange,
            event_type=ExchangeEvent.EventType.COMMENTED,
            request=request,
            user=user if author_type == ExchangeMessage.AuthorType.INTERNAL else None,
            actor_name=actor_name,
            actor_email=actor_email,
            comment=body,
            metadata={
                "exchange_message_id": message.id,
                "exchange_message_author_type": author_type,
            },
        )
    return message


def resolve_exchange_token(token: str) -> DocumentExchange | None:
    token_hash = hash_exchange_token(token or "")
    return (
        DocumentExchange.objects
        .select_related("organization", "document", "document__department", "counterparty", "counterparty_contact", "sent_by")
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
    if comment:
        record_exchange_message(
            exchange=exchange,
            author_type=ExchangeMessage.AuthorType.EXTERNAL,
            body=comment,
            request=request,
            source_event_type=ExchangeEvent.EventType.ACCEPTED,
            create_comment_event=False,
        )
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
    if comment:
        record_exchange_message(
            exchange=exchange,
            author_type=ExchangeMessage.AuthorType.EXTERNAL,
            body=comment,
            request=request,
            source_event_type=ExchangeEvent.EventType.REJECTED,
            create_comment_event=False,
        )
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
def comment_exchange(*, exchange: DocumentExchange, request=None, comment: str) -> ExchangeMessage:
    exchange = DocumentExchange.objects.select_for_update().get(pk=exchange.pk)
    if exchange.is_terminal:
        raise ExchangeError("Exchange is already closed.")
    if not comment:
        raise ExchangeError("Comment is required.")
    return record_exchange_message(
        exchange=exchange,
        author_type=ExchangeMessage.AuthorType.EXTERNAL,
        request=request,
        body=comment,
        source_event_type=ExchangeEvent.EventType.COMMENTED,
    )
