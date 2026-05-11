from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from dms.models import (
    AuditEvent,
    Document,
    ExternalReference,
    IntegrationConnection,
    IntegrationProvider,
    IntegrationSyncJob,
    UsageEvent,
    validate_no_plaintext_secrets,
)
from dms.services.audit import record_audit_event
from dms.services.usage import record_usage_event


STANDARD_PROVIDERS = [
    {
        "code": "email",
        "name": "Email Ingestion",
        "provider_type": IntegrationProvider.ProviderType.EMAIL,
        "description": "Foundation for future inbound email document ingestion.",
    },
    {
        "code": "1c",
        "name": "1C",
        "provider_type": IntegrationProvider.ProviderType.ONE_C,
        "description": "Foundation for future 1C import/export integration.",
    },
    {
        "code": "google-drive",
        "name": "Google Drive",
        "provider_type": IntegrationProvider.ProviderType.GOOGLE_DRIVE,
        "description": "Foundation for future Google Drive integration.",
    },
    {
        "code": "onedrive",
        "name": "OneDrive",
        "provider_type": IntegrationProvider.ProviderType.ONEDRIVE,
        "description": "Foundation for future OneDrive integration.",
    },
    {
        "code": "sharepoint",
        "name": "SharePoint",
        "provider_type": IntegrationProvider.ProviderType.SHAREPOINT,
        "description": "Foundation for future SharePoint integration.",
    },
    {
        "code": "external-api",
        "name": "External API",
        "provider_type": IntegrationProvider.ProviderType.EXTERNAL_API,
        "description": "Foundation for future API-based external systems.",
    },
    {
        "code": "erp",
        "name": "ERP",
        "provider_type": IntegrationProvider.ProviderType.OTHER,
        "description": "Foundation for future ERP integration.",
    },
]


class IntegrationError(ValueError):
    pass


def sanitize_integration_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = metadata or {}
    validate_no_plaintext_secrets(metadata)
    return metadata


def seed_standard_providers() -> list[IntegrationProvider]:
    providers: list[IntegrationProvider] = []
    for provider_data in STANDARD_PROVIDERS:
        provider, _ = IntegrationProvider.objects.update_or_create(
            code=provider_data["code"],
            defaults={
                "name": provider_data["name"],
                "provider_type": provider_data["provider_type"],
                "description": provider_data["description"],
                "is_active": True,
            },
        )
        providers.append(provider)
    return providers


def get_integration_provider(provider_or_code: IntegrationProvider | str) -> IntegrationProvider:
    if isinstance(provider_or_code, IntegrationProvider):
        return provider_or_code
    return IntegrationProvider.objects.get(code=provider_or_code)


@transaction.atomic
def create_integration_connection(
    *,
    organization,
    provider: IntegrationProvider | str,
    name: str,
    user=None,
    status: str = IntegrationConnection.Status.DRAFT,
    credentials_metadata: dict[str, Any] | None = None,
    secret_ref: str = "",
    settings: dict[str, Any] | None = None,
    request=None,
) -> IntegrationConnection:
    provider = get_integration_provider(provider)
    if not provider.is_active:
        raise IntegrationError("Integration provider is inactive.")
    connection = IntegrationConnection(
        organization=organization,
        provider=provider,
        name=(name or provider.name)[:255],
        status=status,
        credentials_metadata=sanitize_integration_metadata(credentials_metadata),
        secret_ref=(secret_ref or "")[:255],
        settings=sanitize_integration_metadata(settings),
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    connection.full_clean()
    connection.save()
    record_audit_event(
        event_type=AuditEvent.EventType.INTEGRATION_CONNECTION_CREATED,
        request=request,
        user=user,
        organization=organization,
        metadata={
            "integration_connection_id": connection.id,
            "integration_provider_id": provider.id,
            "integration_provider_code": provider.code,
            "integration_connection_status": connection.status,
        },
    )
    record_usage_event(
        event_type=UsageEvent.EventType.INTEGRATION_CONNECTION_CREATED,
        organization=organization,
        user=user,
        source="integration",
        metadata={
            "integration_connection_id": connection.id,
            "integration_provider_code": provider.code,
        },
    )
    return connection


@transaction.atomic
def create_integration_sync_job(
    *,
    connection: IntegrationConnection,
    user=None,
    metadata: dict[str, Any] | None = None,
    request=None,
) -> IntegrationSyncJob:
    connection = IntegrationConnection.objects.select_related("organization", "provider").get(pk=connection.pk)
    job = IntegrationSyncJob(
        organization=connection.organization,
        connection=connection,
        status=IntegrationSyncJob.Status.PENDING,
        started_by=user if getattr(user, "is_authenticated", False) else None,
        metadata=sanitize_integration_metadata(metadata),
    )
    job.full_clean()
    job.save()
    record_audit_event(
        event_type=AuditEvent.EventType.INTEGRATION_SYNC_JOB_CREATED,
        request=request,
        user=user,
        organization=connection.organization,
        metadata={
            "integration_sync_job_id": job.id,
            "integration_connection_id": connection.id,
            "integration_provider_code": connection.provider.code,
        },
    )
    record_usage_event(
        event_type=UsageEvent.EventType.INTEGRATION_SYNC_JOB_CREATED,
        organization=connection.organization,
        user=user,
        source="integration",
        metadata={
            "integration_sync_job_id": job.id,
            "integration_connection_id": connection.id,
            "integration_provider_code": connection.provider.code,
        },
    )
    return job


create_sync_job = create_integration_sync_job


@transaction.atomic
def link_external_reference(
    *,
    document: Document,
    connection: IntegrationConnection,
    external_id: str,
    external_type: str = "",
    display_name: str = "",
    external_url: str = "",
    metadata: dict[str, Any] | None = None,
    sync_job: IntegrationSyncJob | None = None,
    user=None,
    request=None,
) -> ExternalReference:
    document = Document.objects.select_related("organization").get(pk=document.pk)
    connection = IntegrationConnection.objects.select_related("organization", "provider").get(pk=connection.pk)
    if document.organization_id != connection.organization_id:
        raise IntegrationError("Document and integration connection belong to different organizations.")
    if sync_job is not None:
        sync_job = IntegrationSyncJob.objects.get(pk=sync_job.pk)
        if sync_job.connection_id != connection.id or sync_job.organization_id != connection.organization_id:
            raise IntegrationError("Sync job does not belong to this connection.")

    reference, _ = ExternalReference.objects.update_or_create(
        connection=connection,
        external_id=(external_id or "").strip()[:512],
        defaults={
            "organization": document.organization,
            "document": document,
            "provider": connection.provider,
            "sync_job": sync_job,
            "external_type": (external_type or "")[:80],
            "display_name": (display_name or "")[:255],
            "external_url": (external_url or "")[:1000],
            "metadata": sanitize_integration_metadata(metadata),
            "last_seen_at": timezone.now(),
        },
    )
    reference.full_clean()
    reference.save()
    if sync_job is not None:
        sync_job.linked_references = ExternalReference.objects.filter(sync_job=sync_job).count()
        sync_job.save(update_fields=["linked_references"])

    record_audit_event(
        event_type=AuditEvent.EventType.EXTERNAL_REFERENCE_LINKED,
        request=request,
        user=user,
        document=document,
        organization=document.organization,
        metadata={
            "external_reference_id": reference.id,
            "integration_connection_id": connection.id,
            "integration_provider_code": connection.provider.code,
            "external_type": reference.external_type,
        },
    )
    record_usage_event(
        event_type=UsageEvent.EventType.EXTERNAL_REFERENCE_LINKED,
        organization=document.organization,
        user=user,
        document=document,
        source="integration",
        metadata={
            "external_reference_id": reference.id,
            "integration_connection_id": connection.id,
            "integration_provider_code": connection.provider.code,
            "external_type": reference.external_type,
        },
    )
    return reference
