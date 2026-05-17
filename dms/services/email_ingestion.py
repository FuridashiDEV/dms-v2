from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from typing import Any, Callable

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone

from dms.forms import validate_uploaded_file
from dms.models import Department, Document, ExternalReference, IntegrationConnection, IntegrationProvider, IntegrationSyncJob
from dms.services.document_creation import create_document_from_uploaded_file
from dms.services.integrations import IntegrationError, link_external_reference
from dms.services.preservation import calculate_file_sha256


class EmailIngestionError(ValueError):
    pass


@dataclass
class EmailAttachmentResult:
    file_name: str
    status: str
    document_id: int | None = None
    document_version_id: int | None = None
    external_reference_id: int | None = None
    error: str = ""


@dataclass
class EmailIngestionResult:
    message_id: str
    sender: str
    subject: str
    received_at: str
    total_attachments: int = 0
    created_documents: int = 0
    skipped_duplicates: int = 0
    rejected_attachments: int = 0
    results: list[EmailAttachmentResult] = field(default_factory=list)


def parse_email_message(raw_message: bytes) -> EmailMessage | Message:
    if not raw_message:
        raise EmailIngestionError("Email message is empty.")
    return BytesParser(policy=policy.default).parsebytes(raw_message)


def _safe_header(message: EmailMessage | Message, header_name: str) -> str:
    value = message.get(header_name, "")
    return str(value or "").strip()


def _message_received_at(message: EmailMessage | Message):
    date_header = _safe_header(message, "Date")
    if not date_header:
        return None
    try:
        parsed = parsedate_to_datetime(date_header)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed is not None and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _fallback_message_id(raw_message: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw_message).hexdigest()}"


def _safe_file_name(file_name: str, index: int) -> str:
    clean_name = os.path.basename(file_name or "").strip()
    if not clean_name:
        clean_name = f"email-attachment-{index}.bin"
    return clean_name[:255]


def _iter_attachments(message: EmailMessage | Message):
    for index, part in enumerate(message.walk(), start=1):
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        file_name = part.get_filename()
        if disposition != "attachment" and not file_name:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        yield index, part, payload


def _attachment_external_id(*, message_id: str, file_name: str, checksum_sha256: str) -> str:
    normalized_message_id = (message_id or "").strip() or "missing-message-id"
    source = f"{normalized_message_id}|{file_name}|{checksum_sha256}"
    return f"email:{hashlib.sha256(source.encode('utf-8')).hexdigest()}"


def _document_title(subject: str, file_name: str) -> str:
    subject = (subject or "").strip()
    if subject:
        return subject[:255]
    return os.path.splitext(os.path.basename(file_name or ""))[0][:255] or "Email attachment"


def _document_description(*, sender: str, subject: str, received_at: str, file_name: str) -> str:
    lines = [
        "Created from inbound email attachment.",
        f"Sender: {sender or 'unknown'}",
        f"Subject: {subject or 'empty'}",
        f"Received at: {received_at or 'unknown'}",
        f"Attachment: {file_name}",
    ]
    return "\n".join(lines)


def _ensure_email_connection(connection: IntegrationConnection) -> IntegrationConnection:
    connection = IntegrationConnection.objects.select_related("organization", "provider").get(pk=connection.pk)
    if connection.provider.provider_type != IntegrationProvider.ProviderType.EMAIL:
        raise EmailIngestionError("Integration connection must use an email provider.")
    return connection


def _ensure_same_organization(connection: IntegrationConnection, department: Department) -> None:
    if connection.organization_id != department.organization_id:
        raise EmailIngestionError("Email ingestion connection and target department belong to different organizations.")


def ingest_email_message(
    *,
    raw_message: bytes,
    connection: IntegrationConnection,
    department: Department,
    uploaded_by=None,
    folder=None,
    sync_job: IntegrationSyncJob | None = None,
    request=None,
    run_ai: bool = False,
    parser=None,
    text_extractor=None,
    indexer: Callable[[Document], Any] | None = None,
) -> EmailIngestionResult:
    connection = _ensure_email_connection(connection)
    department = Department.objects.select_related("organization").get(pk=department.pk)
    _ensure_same_organization(connection, department)
    if folder is not None and folder.department_id != department.id:
        raise EmailIngestionError("Email ingestion folder must belong to the target department.")
    if sync_job is not None:
        sync_job = IntegrationSyncJob.objects.get(pk=sync_job.pk)
        if sync_job.connection_id != connection.id or sync_job.organization_id != connection.organization_id:
            raise EmailIngestionError("Email ingestion sync job does not belong to this connection.")

    message = parse_email_message(raw_message)
    sender = _safe_header(message, "From")[:255]
    subject = _safe_header(message, "Subject")[:255]
    message_id = _safe_header(message, "Message-ID")[:255] or _fallback_message_id(raw_message)
    received_at_value = _message_received_at(message)
    received_at = received_at_value.isoformat() if received_at_value else ""
    result = EmailIngestionResult(
        message_id=message_id,
        sender=sender,
        subject=subject,
        received_at=received_at,
    )

    if sync_job is not None:
        sync_job.status = IntegrationSyncJob.Status.RUNNING
        sync_job.started_at = sync_job.started_at or timezone.now()
        sync_job.save(update_fields=["status", "started_at"])

    for index, part, payload in _iter_attachments(message):
        file_name = _safe_file_name(part.get_filename() or "", index)
        uploaded_file = SimpleUploadedFile(
            file_name,
            payload,
            content_type=(part.get_content_type() or "application/octet-stream"),
        )
        checksum_sha256 = calculate_file_sha256(uploaded_file)
        external_id = _attachment_external_id(
            message_id=message_id,
            file_name=file_name,
            checksum_sha256=checksum_sha256,
        )
        result.total_attachments += 1

        existing_reference = ExternalReference.objects.filter(connection=connection, external_id=external_id).first()
        if existing_reference is not None:
            result.skipped_duplicates += 1
            result.results.append(
                EmailAttachmentResult(
                    file_name=file_name,
                    status="duplicate",
                    document_id=existing_reference.document_id,
                    external_reference_id=existing_reference.id,
                )
            )
            continue

        try:
            validate_uploaded_file(uploaded_file)
            uploaded_file.seek(0)
        except ValidationError as exc:
            result.rejected_attachments += 1
            result.results.append(
                EmailAttachmentResult(
                    file_name=file_name,
                    status="rejected",
                    error="; ".join(str(message) for message in exc.messages)[:1000],
                )
            )
            continue

        metadata = {
            "message_id": message_id,
            "sender": sender,
            "subject": subject,
            "received_at": received_at,
            "attachment_file_name": file_name,
            "attachment_content_type": uploaded_file.content_type or "",
            "attachment_sha256": checksum_sha256,
        }
        mailbox = (connection.settings or {}).get("mailbox")
        if mailbox:
            metadata["mailbox"] = str(mailbox)[:255]

        create_kwargs = {
            "uploaded_file": uploaded_file,
            "department": department,
            "folder": folder,
            "title": _document_title(subject, file_name),
            "description": _document_description(
                sender=sender,
                subject=subject,
                received_at=received_at,
                file_name=file_name,
            ),
            "source_system": "email_ingestion",
            "uploaded_by": uploaded_by,
            "request": request,
            "run_ai": run_ai,
            "audit_metadata": {
                "email_message_id": message_id,
                "email_sender": sender,
                "email_attachment_file_name": file_name,
                "integration_connection_id": connection.id,
                "integration_sync_job_id": sync_job.id if sync_job else None,
            },
        }
        if parser is not None:
            create_kwargs["parser"] = parser
        if text_extractor is not None:
            create_kwargs["text_extractor"] = text_extractor
        if indexer is not None:
            create_kwargs["indexer"] = indexer

        with transaction.atomic():
            document, version = create_document_from_uploaded_file(**create_kwargs)
            reference = link_external_reference(
                document=document,
                connection=connection,
                sync_job=sync_job,
                external_id=external_id,
                external_type="email_attachment",
                display_name=file_name,
                metadata=metadata,
                user=uploaded_by,
                request=request,
            )

        result.created_documents += 1
        result.results.append(
            EmailAttachmentResult(
                file_name=file_name,
                status="created",
                document_id=document.id,
                document_version_id=version.id,
                external_reference_id=reference.id,
            )
        )

    if sync_job is not None:
        sync_job.total_items = result.total_attachments
        sync_job.processed_items = result.created_documents + result.skipped_duplicates
        sync_job.created_documents = result.created_documents
        sync_job.linked_references = ExternalReference.objects.filter(sync_job=sync_job).count()
        sync_job.failed_items = result.rejected_attachments
        sync_job.status = IntegrationSyncJob.Status.COMPLETED
        sync_job.completed_at = timezone.now()
        sync_job.save(
            update_fields=[
                "total_items",
                "processed_items",
                "created_documents",
                "linked_references",
                "failed_items",
                "status",
                "completed_at",
            ]
        )
    connection.last_sync_at = timezone.now()
    connection.save(update_fields=["last_sync_at"])

    return result


def ingest_email_message_from_file(*, file_path: str, **kwargs) -> EmailIngestionResult:
    with open(file_path, "rb") as source:
        return ingest_email_message(raw_message=source.read(), **kwargs)
