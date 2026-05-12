from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from django.db.models import Q
from django.utils import timezone

from dms.models import (
    AuditEvent,
    Document,
    DocumentExchange,
    DocumentRelation,
    ExchangeEvent,
    ExchangeMessage,
    ExtractedField,
    ProcessingJob,
    WorkflowAction,
    WorkflowInstance,
)
from dms.utils import get_allowed_documents


SENSITIVE_KEY_PARTS = ("token", "secret", "api_key", "apikey", "password", "private_key", "portal_url")


def _dt(value) -> str | None:
    return value.isoformat() if value else None


def _date(value) -> str | None:
    return value.isoformat() if value else None


def _decimal(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _user_ref(user) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.get_full_name() or user.username,
        "email": user.email or "",
    }


def _organization_ref(organization) -> dict[str, Any]:
    return {
        "id": organization.id,
        "name": organization.name,
        "slug": organization.slug,
    }


def _department_ref(department) -> dict[str, Any] | None:
    if department is None:
        return None
    return {
        "id": department.id,
        "name": department.name,
        "organization_id": department.organization_id,
    }


def _folder_ref(folder) -> dict[str, Any] | None:
    if folder is None:
        return None
    return {
        "id": folder.id,
        "name": folder.name,
        "department_id": folder.department_id,
    }


def _document_type_ref(doc_type) -> dict[str, Any] | None:
    if doc_type is None:
        return None
    return {
        "id": doc_type.id,
        "name": doc_type.name,
    }


def _counterparty_ref(counterparty) -> dict[str, Any] | None:
    if counterparty is None:
        return None
    return {
        "id": counterparty.id,
        "name": counterparty.name,
        "email": counterparty.email or "",
        "contact_name": counterparty.contact_name or "",
        "organization_id": counterparty.organization_id,
        "is_active": counterparty.is_active,
    }


def _counterparty_contact_ref(contact) -> dict[str, Any] | None:
    if contact is None:
        return None
    return {
        "id": contact.id,
        "counterparty_id": contact.counterparty_id,
        "name": contact.name,
        "email": contact.email or "",
        "position": contact.position or "",
        "phone": contact.phone or "",
        "is_active": contact.is_active,
    }


def _document_relation_ref(relation: DocumentRelation, *, source_document: Document) -> dict[str, Any]:
    if relation.from_document_id == source_document.id:
        related_document = relation.to_document
        direction = "outgoing"
    else:
        related_document = relation.from_document
        direction = "incoming"
    return {
        "id": relation.id,
        "direction": direction,
        "relation_type": relation.relation_type,
        "relation_type_display": relation.get_relation_type_display(),
        "related_document": {
            "id": related_document.id,
            "public_id": str(related_document.public_id) if related_document.public_id else "",
            "title": related_document.title,
            "status": related_document.status,
            "document_type": _document_type_ref(related_document.doc_type),
            "document_date": _date(related_document.doc_date),
            "department": _department_ref(related_document.department),
            "checksum_sha256": related_document.checksum_sha256,
        },
        "created_at": _dt(relation.created_at),
    }


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        safe = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
                continue
            else:
                safe[str(key)] = _sanitize(item)
        return safe
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    return value


def build_document_evidence_package(*, document: Document, exported_by=None) -> dict[str, Any]:
    document = (
        Document.objects
        .select_related("organization", "department", "folder", "doc_type", "uploaded_by")
        .get(pk=document.pk)
    )
    organization = document.organization

    versions = (
        document.versions
        .filter(organization=organization)
        .select_related("doc_type", "department", "folder", "uploaded_by")
        .order_by("number", "id")
    )
    processing_jobs = (
        ProcessingJob.objects
        .filter(document=document, organization=organization)
        .select_related("created_by")
        .prefetch_related("fields")
        .order_by("created_at", "id")
    )
    workflow_instances = (
        WorkflowInstance.objects
        .filter(document=document, organization=organization)
        .select_related("template", "current_step_template", "started_by")
        .prefetch_related("actions")
        .order_by("started_at", "id")
    )
    exchanges = (
        DocumentExchange.objects
        .filter(document=document, organization=organization)
        .select_related("counterparty", "counterparty_contact", "sent_by", "received_by")
        .prefetch_related("events", "messages")
        .order_by("created_at", "id")
    )
    audit_events = (
        AuditEvent.objects
        .filter(document=document, organization=organization)
        .select_related("user", "document_version")
        .order_by("created_at", "id")
    )
    if exported_by is not None:
        visible_document_ids = get_allowed_documents(exported_by).filter(
            organization=organization,
        ).values("id")
    else:
        visible_document_ids = Document.objects.filter(
            organization=organization,
        ).values("id")
    related_documents = (
        DocumentRelation.objects
        .filter(
            Q(from_document=document, to_document_id__in=visible_document_ids)
            | Q(to_document=document, from_document_id__in=visible_document_ids)
        )
        .filter(from_document__organization=organization, to_document__organization=organization)
        .select_related(
            "from_document",
            "from_document__department",
            "from_document__doc_type",
            "to_document",
            "to_document__department",
            "to_document__doc_type",
        )
        .order_by("relation_type", "created_at", "id")
    )

    return {
        "schema": {
            "name": "dms.legal_evidence_package",
            "version": "1.0",
        },
        "export": {
            "generated_at": _dt(timezone.now()),
            "generated_by": _user_ref(exported_by),
            "format": "json",
        },
        "organization": _organization_ref(organization),
        "document": {
            "id": document.id,
            "public_id": str(document.public_id) if document.public_id else "",
            "title": document.title,
            "description": document.description,
            "status": document.status,
            "document_type": _document_type_ref(document.doc_type),
            "document_date": _date(document.doc_date),
            "department": _department_ref(document.department),
            "folder": _folder_ref(document.folder),
            "language": document.language,
            "document_author": document.document_author,
            "retention_category": document.retention_category,
            "retention_until": _date(document.retention_until),
            "legal_hold": document.legal_hold,
            "source_file_name": document.source_file_name,
            "mime_type": document.mime_type,
            "checksum_sha256": document.checksum_sha256,
            "source_system": document.source_system,
            "format_risk_level": document.format_risk_level,
            "uploaded_by": _user_ref(document.uploaded_by),
            "created_at": _dt(document.created_at),
        },
        "versions": [
            {
                "id": version.id,
                "number": version.number,
                "title": version.title,
                "description": version.description,
                "status": version.status,
                "document_type": _document_type_ref(version.doc_type),
                "document_date": _date(version.doc_date),
                "department": _department_ref(version.department),
                "folder": _folder_ref(version.folder),
                "language": version.language,
                "document_author": version.document_author,
                "retention_category": version.retention_category,
                "retention_until": _date(version.retention_until),
                "legal_hold": version.legal_hold,
                "source_file_name": version.source_file_name,
                "mime_type": version.mime_type,
                "checksum_sha256": version.checksum_sha256,
                "source_system": version.source_system,
                "format_risk_level": version.format_risk_level,
                "uploaded_by": _user_ref(version.uploaded_by),
                "created_at": _dt(version.created_at),
            }
            for version in versions
        ],
        "related_documents": [
            _document_relation_ref(relation, source_document=document)
            for relation in related_documents
        ],
        "ai": {
            "processing_jobs": [
                {
                    "id": job.id,
                    "status": job.status,
                    "source": job.source,
                    "parser_name": job.parser_name,
                    "extracted_text_length": job.extracted_text_length,
                    "error_message": job.error_message,
                    "created_by": _user_ref(job.created_by),
                    "created_at": _dt(job.created_at),
                    "started_at": _dt(job.started_at),
                    "completed_at": _dt(job.completed_at),
                    "fields": [
                        {
                            "id": field.id,
                            "field_name": field.field_name,
                            "label": field.label,
                            "value": field.value,
                            "confidence": _decimal(field.confidence),
                            "status": field.status,
                            "reviewed_by": _user_ref(field.reviewed_by),
                            "reviewed_at": _dt(field.reviewed_at),
                            "applied_at": _dt(field.applied_at),
                            "created_at": _dt(field.created_at),
                            "updated_at": _dt(field.updated_at),
                        }
                        for field in job.fields.all()
                        if field.organization_id == organization.id and field.document_id == document.id
                    ],
                }
                for job in processing_jobs
            ],
            "fields": [
                {
                    "id": field.id,
                    "job_id": field.job_id,
                    "field_name": field.field_name,
                    "label": field.label,
                    "value": field.value,
                    "confidence": _decimal(field.confidence),
                    "status": field.status,
                    "reviewed_by": _user_ref(field.reviewed_by),
                    "reviewed_at": _dt(field.reviewed_at),
                    "applied_at": _dt(field.applied_at),
                    "created_at": _dt(field.created_at),
                    "updated_at": _dt(field.updated_at),
                }
                for field in ExtractedField.objects
                .filter(document=document, organization=organization)
                .select_related("reviewed_by")
                .order_by("created_at", "id")
            ],
        },
        "workflow": [
            {
                "id": instance.id,
                "template": {
                    "id": instance.template_id,
                    "name": instance.template.name,
                },
                "status": instance.status,
                "current_step": {
                    "id": instance.current_step_template_id,
                    "name": instance.current_step_template.name,
                } if instance.current_step_template else None,
                "started_by": _user_ref(instance.started_by),
                "started_at": _dt(instance.started_at),
                "completed_at": _dt(instance.completed_at),
                "actions": [
                    {
                        "id": action.id,
                        "action_type": action.action_type,
                        "step": {
                            "id": action.step_template_id,
                            "name": action.step_template.name,
                        } if action.step_template else None,
                        "actor": _user_ref(action.actor),
                        "comment": action.comment,
                        "created_at": _dt(action.created_at),
                    }
                    for action in WorkflowAction.objects
                    .filter(instance=instance, document=document, organization=organization)
                    .select_related("step_template", "actor")
                    .order_by("created_at", "id")
                ],
            }
            for instance in workflow_instances
        ],
        "exchanges": [
            {
                "id": exchange.id,
                "direction": exchange.direction,
                "status": exchange.status,
                "business_document_type": exchange.business_document_type,
                "counterparty": _counterparty_ref(exchange.counterparty),
                "counterparty_contact": _counterparty_contact_ref(exchange.counterparty_contact),
                "sent_by": _user_ref(exchange.sent_by),
                "received_by": _user_ref(exchange.received_by),
                "message": exchange.message,
                "expires_at": _dt(exchange.expires_at),
                "opened_at": _dt(exchange.opened_at),
                "received_at": _dt(exchange.received_at),
                "responded_at": _dt(exchange.responded_at),
                "created_at": _dt(exchange.created_at),
                "updated_at": _dt(exchange.updated_at),
                "events": [
                    {
                        "id": event.id,
                        "event_type": event.event_type,
                        "actor_name": event.actor_name,
                        "actor_email": event.actor_email,
                        "comment": event.comment,
                        "ip_address": event.ip_address,
                        "user_agent": event.user_agent,
                        "created_at": _dt(event.created_at),
                    }
                    for event in ExchangeEvent.objects
                    .filter(exchange=exchange, document=document, organization=organization)
                    .order_by("created_at", "id")
                ],
                "messages": [
                    {
                        "id": message.id,
                        "author_type": message.author_type,
                        "user": _user_ref(message.user),
                        "counterparty_contact": _counterparty_contact_ref(message.counterparty_contact),
                        "body": message.body,
                        "source_event_type": message.source_event_type,
                        "ip_address": message.ip_address,
                        "user_agent": message.user_agent,
                        "created_at": _dt(message.created_at),
                    }
                    for message in ExchangeMessage.objects
                    .filter(exchange=exchange, document=document, organization=organization)
                    .select_related("user", "counterparty_contact")
                    .order_by("created_at", "id")
                ],
            }
            for exchange in exchanges
        ],
        "audit_events": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "user": _user_ref(event.user),
                "document_version_id": event.document_version_id,
                "ip_address": event.ip_address,
                "user_agent": event.user_agent,
                "metadata": _sanitize(event.metadata),
                "created_at": _dt(event.created_at),
            }
            for event in audit_events
        ],
    }
