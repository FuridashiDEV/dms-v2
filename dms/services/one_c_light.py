from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone

from dms.forms import validate_uploaded_file
from dms.models import Department, Document, ExternalReference, ExtractedField, IntegrationConnection, IntegrationProvider, IntegrationSyncJob
from dms.services.document_creation import create_document_from_uploaded_file
from dms.services.integrations import link_external_reference, sanitize_integration_metadata
from dms.services.preservation import calculate_file_sha256


class OneCLightError(ValueError):
    pass


CONFIRMED_EXPORT_STATUSES = {
    ExtractedField.Status.CONFIRMED,
    ExtractedField.Status.APPLIED,
}


@dataclass
class OneCLightImportResult:
    status: str
    external_id: str
    object_type: str
    document_id: int | None = None
    document_version_id: int | None = None
    external_reference_id: int | None = None
    error: str = ""


def make_1c_light_uploaded_file(*, content: bytes, file_name: str, content_type: str = "") -> SimpleUploadedFile:
    safe_name = os.path.basename(file_name or "").strip()[:255] or "1c-light-payload.json"
    return SimpleUploadedFile(safe_name, content or b"", content_type=content_type or "application/octet-stream")


def _ensure_1c_connection(connection: IntegrationConnection) -> IntegrationConnection:
    connection = IntegrationConnection.objects.select_related("organization", "provider").get(pk=connection.pk)
    if connection.provider.provider_type != IntegrationProvider.ProviderType.ONE_C:
        raise OneCLightError("Integration connection must use the 1C provider.")
    return connection


def _ensure_same_organization(connection: IntegrationConnection, department: Department) -> None:
    if connection.organization_id != department.organization_id:
        raise OneCLightError("1C connection and target department belong to different organizations.")


def _default_title(uploaded_file, external_id: str) -> str:
    file_title = os.path.splitext(os.path.basename(getattr(uploaded_file, "name", "") or ""))[0].strip()
    return (file_title or external_id or "1C document")[:255]


def _external_type(object_type: str) -> str:
    return (object_type or "1c_object").strip()[:80] or "1c_object"


def _metadata(
    *,
    uploaded_file,
    checksum_sha256: str,
    object_type: str,
    source_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    metadata = sanitize_integration_metadata(source_metadata)
    metadata.update(
        {
            "source": "1c_light",
            "object_type": _external_type(object_type),
            "file_name": os.path.basename(getattr(uploaded_file, "name", "") or ""),
            "file_sha256": checksum_sha256,
            "content_type": getattr(uploaded_file, "content_type", "") or "",
        }
    )
    return sanitize_integration_metadata(metadata)


def import_1c_light_document(
    *,
    uploaded_file,
    connection: IntegrationConnection,
    department: Department,
    external_id: str,
    object_type: str = "",
    title: str = "",
    description: str = "",
    metadata: dict[str, Any] | None = None,
    uploaded_by=None,
    folder=None,
    sync_job: IntegrationSyncJob | None = None,
    request=None,
    run_ai: bool = False,
    parser=None,
    text_extractor=None,
    indexer: Callable[[Document], Any] | None = None,
) -> OneCLightImportResult:
    external_id = (external_id or "").strip()
    if not external_id:
        raise OneCLightError("1C external_id is required.")

    connection = _ensure_1c_connection(connection)
    department = Department.objects.select_related("organization").get(pk=department.pk)
    _ensure_same_organization(connection, department)
    if folder is not None and folder.department_id != department.id:
        raise OneCLightError("1C import folder must belong to the target department.")
    if sync_job is not None:
        sync_job = IntegrationSyncJob.objects.get(pk=sync_job.pk)
        if sync_job.connection_id != connection.id or sync_job.organization_id != connection.organization_id:
            raise OneCLightError("1C sync job does not belong to this connection.")

    existing_reference = ExternalReference.objects.filter(connection=connection, external_id=external_id).first()
    if existing_reference is not None:
        return OneCLightImportResult(
            status="duplicate",
            external_id=external_id,
            object_type=_external_type(object_type or existing_reference.external_type),
            document_id=existing_reference.document_id,
            external_reference_id=existing_reference.id,
        )

    try:
        validate_uploaded_file(uploaded_file)
        uploaded_file.seek(0)
    except ValidationError as exc:
        return OneCLightImportResult(
            status="rejected",
            external_id=external_id,
            object_type=_external_type(object_type),
            error="; ".join(str(message) for message in exc.messages)[:1000],
        )

    checksum_sha256 = calculate_file_sha256(uploaded_file)
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    reference_metadata = _metadata(
        uploaded_file=uploaded_file,
        checksum_sha256=checksum_sha256,
        object_type=object_type,
        source_metadata=metadata,
    )

    create_kwargs = {
        "uploaded_file": uploaded_file,
        "department": department,
        "folder": folder,
        "title": (title or _default_title(uploaded_file, external_id))[:255],
        "description": description or "Created from 1C-light import.",
        "source_system": "1c_light",
        "uploaded_by": uploaded_by,
        "request": request,
        "run_ai": run_ai,
        "audit_metadata": {
            "integration_connection_id": connection.id,
            "integration_sync_job_id": sync_job.id if sync_job else None,
            "1c_external_id": external_id,
            "1c_object_type": _external_type(object_type),
        },
    }
    if parser is not None:
        create_kwargs["parser"] = parser
    if text_extractor is not None:
        create_kwargs["text_extractor"] = text_extractor
    if indexer is not None:
        create_kwargs["indexer"] = indexer

    if sync_job is not None:
        sync_job.status = IntegrationSyncJob.Status.RUNNING
        sync_job.started_at = sync_job.started_at or timezone.now()
        sync_job.save(update_fields=["status", "started_at"])

    with transaction.atomic():
        document, version = create_document_from_uploaded_file(**create_kwargs)
        reference = link_external_reference(
            document=document,
            connection=connection,
            sync_job=sync_job,
            external_id=external_id,
            external_type=_external_type(object_type),
            display_name=f"{_external_type(object_type)} {external_id}"[:255],
            metadata=reference_metadata,
            user=uploaded_by,
            request=request,
        )

    if sync_job is not None:
        sync_job.total_items = 1
        sync_job.processed_items = 1
        sync_job.created_documents = 1
        sync_job.linked_references = ExternalReference.objects.filter(sync_job=sync_job).count()
        sync_job.status = IntegrationSyncJob.Status.COMPLETED
        sync_job.completed_at = timezone.now()
        sync_job.save(
            update_fields=[
                "total_items",
                "processed_items",
                "created_documents",
                "linked_references",
                "status",
                "completed_at",
            ]
        )

    connection.last_sync_at = timezone.now()
    connection.save(update_fields=["last_sync_at"])

    return OneCLightImportResult(
        status="created",
        external_id=external_id,
        object_type=_external_type(object_type),
        document_id=document.id,
        document_version_id=version.id,
        external_reference_id=reference.id,
    )


def build_1c_light_export_payload(
    *,
    document: Document,
    connection: IntegrationConnection | None = None,
) -> dict[str, Any]:
    document = Document.objects.select_related("organization", "department", "doc_type").get(pk=document.pk)
    reference_qs = (
        ExternalReference.objects
        .select_related("connection", "provider")
        .filter(document=document, provider__provider_type=IntegrationProvider.ProviderType.ONE_C)
        .order_by("-last_seen_at", "-id")
    )

    if connection is not None:
        connection = _ensure_1c_connection(connection)
        if connection.organization_id != document.organization_id:
            raise OneCLightError("1C connection and document belong to different organizations.")
        reference_qs = reference_qs.filter(connection=connection)

    reference = reference_qs.first()
    confirmed_fields = (
        ExtractedField.objects
        .filter(document=document, status__in=CONFIRMED_EXPORT_STATUSES)
        .select_related("reviewed_by")
        .order_by("field_name", "id")
    )

    fields = {}
    for field in confirmed_fields:
        fields[field.field_name] = {
            "label": field.label,
            "value": field.value,
            "status": field.status,
            "reviewed_at": field.reviewed_at.isoformat() if field.reviewed_at else "",
            "applied_at": field.applied_at.isoformat() if field.applied_at else "",
        }

    return {
        "export_type": "1c_light_confirmed_fields",
        "export_scope": "confirmed_or_applied_fields_only",
        "document": {
            "id": document.id,
            "public_id": str(document.public_id),
            "title": document.title,
            "status": document.status,
            "doc_date": document.doc_date.isoformat() if document.doc_date else "",
            "department_id": document.department_id,
            "doc_type": document.doc_type.name if document.doc_type_id else "",
            "checksum_sha256": document.checksum_sha256,
            "source_system": document.source_system,
        },
        "external_reference": {
            "external_id": reference.external_id if reference else "",
            "object_type": reference.external_type if reference else "",
            "provider": reference.provider.code if reference else "1c",
            "connection_id": reference.connection_id if reference else None,
        },
        "confirmed_fields": fields,
    }
