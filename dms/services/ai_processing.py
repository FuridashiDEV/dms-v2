from __future__ import annotations

from datetime import date
from typing import Callable

from django.db import transaction
from django.utils import timezone

from dms.models import AuditEvent, Document, DocumentType, ExtractedField, ProcessingJob, UsageEvent
from dms.services.audit import record_audit_event
from dms.services.ai_parser import parse_document
from dms.services.document_metadata import extract_candidate_dates
from dms.services.notifications import notify_ai_review_ready
from dms.services.usage import record_usage_event


FIELD_LABELS = {
    "title": "Название",
    "description": "Описание",
    "doc_date": "Дата документа",
    "doc_type": "Тип документа",
    "language": "Язык",
    "document_author": "Автор документа",
    "retention_category": "Категория хранения",
    "legal_hold": "Legal hold",
}

APPLICABLE_FIELDS = set(FIELD_LABELS)


def _string_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def build_ai_field_suggestions(meta: dict, candidate_dates: list[date]) -> dict[str, str]:
    suggestions = {
        "title": _string_value(meta.get("title_ru")),
        "description": _string_value(meta.get("summary_ru")),
        "doc_type": _string_value(meta.get("doc_type")),
        "language": _string_value(meta.get("language")),
        "document_author": _string_value(meta.get("document_author")),
        "retention_category": _string_value(meta.get("retention_category")),
        "legal_hold": _string_value(meta.get("legal_hold")),
    }

    idx = meta.get("date_index")
    if isinstance(idx, int) and 0 <= idx < len(candidate_dates):
        suggestions["doc_date"] = candidate_dates[idx].isoformat()
    else:
        suggestions["doc_date"] = ""

    return {
        field_name: value
        for field_name, value in suggestions.items()
        if value not in {"", "UNKNOWN", "false"}
    }


@transaction.atomic
def run_document_ai_processing(
    *,
    document: Document,
    text: str,
    user=None,
    request=None,
    source: str = ProcessingJob.Source.MANUAL,
    parser: Callable[..., dict] = parse_document,
) -> ProcessingJob:
    job = ProcessingJob.objects.create(
        organization=document.organization,
        document=document,
        created_by=user if getattr(user, "is_authenticated", False) else None,
        status=ProcessingJob.Status.RUNNING,
        source=source,
        extracted_text_length=len(text or ""),
        started_at=timezone.now(),
    )
    record_audit_event(
        event_type=AuditEvent.EventType.AI_PROCESSING_STARTED,
        request=request,
        document=document,
        metadata={"processing_job_id": job.id, "source": source},
    )
    record_usage_event(
        event_type=UsageEvent.EventType.AI_PROCESSING_STARTED,
        user=user,
        document=document,
        source=source,
        metadata={
            "processing_job_id": job.id,
            "text_length": len(text or ""),
        },
    )

    try:
        candidate_dates = extract_candidate_dates(text or "")
        allowed_types = set(
            DocumentType.objects.filter(
                organization=document.organization,
            ).values_list("name", flat=True)
        )
        meta = parser(
            text=text or "",
            candidate_dates=candidate_dates,
            allowed_doc_types=allowed_types,
        )
        if not isinstance(meta, dict):
            meta = {}

        job.raw_result = meta
        job.status = ProcessingJob.Status.COMPLETED
        job.completed_at = timezone.now()
        job.save(update_fields=["raw_result", "status", "completed_at"])

        for field_name, value in build_ai_field_suggestions(meta, candidate_dates).items():
            ExtractedField.objects.update_or_create(
                job=job,
                field_name=field_name,
                defaults={
                    "organization": document.organization,
                    "document": document,
                    "label": FIELD_LABELS[field_name],
                    "value": value,
                    "status": ExtractedField.Status.SUGGESTED,
                },
            )

        record_audit_event(
            event_type=AuditEvent.EventType.AI_PROCESSING_COMPLETED,
            request=request,
            document=document,
            metadata={
                "processing_job_id": job.id,
                "source": source,
                "field_count": job.fields.count(),
            },
        )
        record_usage_event(
            event_type=UsageEvent.EventType.AI_PROCESSING_COMPLETED,
            user=user,
            document=document,
            source=source,
            quantity=max(job.fields.count(), 1),
            metadata={
                "processing_job_id": job.id,
                "field_count": job.fields.count(),
            },
        )
        notify_ai_review_ready(job=job, actor=user)
    except Exception as exc:
        job.status = ProcessingJob.Status.FAILED
        job.error_message = str(exc)[:2000]
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "error_message", "completed_at"])
        record_audit_event(
            event_type=AuditEvent.EventType.AI_PROCESSING_FAILED,
            request=request,
            document=document,
            metadata={
                "processing_job_id": job.id,
                "source": source,
                "error": job.error_message,
            },
        )
        record_usage_event(
            event_type=UsageEvent.EventType.AI_PROCESSING_FAILED,
            user=user,
            document=document,
            source=source,
            metadata={
                "processing_job_id": job.id,
            },
        )

    return job


def coerce_field_value(*, field_name: str, value: str, document: Document):
    value = (value or "").strip()
    if field_name == "doc_date":
        if not value:
            return None
        return date.fromisoformat(value)
    if field_name == "doc_type":
        if not value:
            return None
        doc_type, _ = DocumentType.objects.get_or_create(
            organization=document.organization,
            name=value[:100],
        )
        return doc_type
    if field_name == "language":
        allowed = {choice[0] for choice in Document.Language.choices}
        return value if value in allowed else Document.Language.UNKNOWN
    if field_name == "legal_hold":
        return value.lower() in {"1", "true", "yes", "on", "да"}
    if field_name in {
        "title",
        "description",
        "document_author",
        "retention_category",
    }:
        return value
    raise ValueError(f"Unsupported AI field: {field_name}")


@transaction.atomic
def apply_confirmed_fields(*, job: ProcessingJob, user, request=None) -> list[str]:
    document = job.document
    applied_fields: list[str] = []

    for field in job.fields.select_for_update().filter(status=ExtractedField.Status.CONFIRMED):
        if field.field_name not in APPLICABLE_FIELDS:
            continue
        value = coerce_field_value(
            field_name=field.field_name,
            value=field.value,
            document=document,
        )
        setattr(document, field.field_name, value)
        field.status = ExtractedField.Status.APPLIED
        field.applied_at = timezone.now()
        field.save(update_fields=["status", "applied_at", "updated_at"])
        applied_fields.append(field.field_name)

    if applied_fields:
        document.save(update_fields=applied_fields)
        document.create_version(uploaded_by=user)
        record_audit_event(
            event_type=AuditEvent.EventType.AI_FIELDS_APPLIED,
            request=request,
            document=document,
            metadata={
                "processing_job_id": job.id,
                "applied_fields": applied_fields,
            },
        )

    if not job.fields.exclude(
        status__in=[ExtractedField.Status.APPLIED, ExtractedField.Status.REJECTED]
    ).exists():
        job.status = ProcessingJob.Status.REVIEWED
        job.save(update_fields=["status"])

    return applied_fields
