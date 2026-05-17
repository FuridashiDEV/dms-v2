from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from django.db.models import Avg, Count, Sum
from django.utils import timezone

from dms.models import (
    Counterparty,
    Document,
    DocumentExchange,
    DocumentSearchIndexState,
    ExtractedField,
    ObservabilityAlert,
    ObservabilityMetric,
    Organization,
    ProcessingJob,
    UsageEvent,
    WorkflowInstance,
)
from dms.services.observability import build_gpu_metrics_foundation, evaluate_observability_alerts, record_queue_snapshot


DEFAULT_RANGE_DAYS = 30


def parse_date_range(params) -> dict[str, Any]:
    today = timezone.localdate()
    default_start = today - timedelta(days=DEFAULT_RANGE_DAYS - 1)

    def parse_date(value: str | None, fallback: date) -> date:
        if not value:
            return fallback
        try:
            return date.fromisoformat(value)
        except ValueError:
            return fallback

    start_date = parse_date(params.get("start"), default_start)
    end_date = parse_date(params.get("end"), today)
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    current_tz = timezone.get_current_timezone()
    starts_at = timezone.make_aware(datetime.combine(start_date, time.min), current_tz)
    ends_at = timezone.make_aware(datetime.combine(end_date + timedelta(days=1), time.min), current_tz)
    return {
        "start": start_date,
        "end": end_date,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }


def _range_filter(field_name: str, date_range: dict[str, Any]) -> dict[str, Any]:
    return {
        f"{field_name}__gte": date_range["starts_at"],
        f"{field_name}__lt": date_range["ends_at"],
    }


def _usage_summary(organizations, date_range: dict[str, Any]) -> list[dict[str, Any]]:
    return list(
        UsageEvent.objects.filter(
            organization__in=organizations,
            **_range_filter("created_at", date_range),
        )
        .values("event_type")
        .annotate(events=Count("id"), quantity=Sum("quantity"))
        .order_by("event_type")
    )


def build_organization_metrics(organization: Organization, date_range: dict[str, Any]) -> dict[str, Any]:
    organization_qs = Organization.objects.filter(id=organization.id)
    document_filters = {"organization": organization, **_range_filter("created_at", date_range)}
    usage_filters = {"organization": organization, **_range_filter("created_at", date_range)}

    workflow_completed_statuses = [
        WorkflowInstance.Status.APPROVED,
        WorkflowInstance.Status.REJECTED,
        WorkflowInstance.Status.CANCELED,
    ]
    ai_reviewed_statuses = [
        ExtractedField.Status.CONFIRMED,
        ExtractedField.Status.APPLIED,
    ]

    return {
        "organization": organization,
        "documents_uploaded": Document.objects.filter(**document_filters).count(),
        "documents_total": Document.objects.filter(organization=organization).count(),
        "ai_documents_processed": ProcessingJob.objects.filter(
            organization=organization,
            status=ProcessingJob.Status.COMPLETED,
            completed_at__gte=date_range["starts_at"],
            completed_at__lt=date_range["ends_at"],
        ).count(),
        "ai_fields_confirmed": ExtractedField.objects.filter(
            organization=organization,
            status__in=ai_reviewed_statuses,
            updated_at__gte=date_range["starts_at"],
            updated_at__lt=date_range["ends_at"],
        ).count(),
        "workflow_started": WorkflowInstance.objects.filter(
            organization=organization,
            **_range_filter("started_at", date_range),
        ).count(),
        "workflow_completed": WorkflowInstance.objects.filter(
            organization=organization,
            status__in=workflow_completed_statuses,
            completed_at__gte=date_range["starts_at"],
            completed_at__lt=date_range["ends_at"],
        ).count(),
        "documents_sent_to_counterparties": DocumentExchange.objects.filter(
            organization=organization,
            direction=DocumentExchange.Direction.OUTGOING,
            **_range_filter("created_at", date_range),
        ).count(),
        "counterparties_created": Counterparty.objects.filter(
            organization=organization,
            **_range_filter("created_at", date_range),
        ).count(),
        "evidence_exports": UsageEvent.objects.filter(
            event_type=UsageEvent.EventType.EVIDENCE_EXPORTED,
            **usage_filters,
        ).aggregate(quantity=Sum("quantity"))["quantity"]
        or 0,
        "usage_summary": _usage_summary(organization_qs, date_range),
    }


def build_platform_metrics(date_range: dict[str, Any]) -> dict[str, Any]:
    organizations = Organization.objects.filter(is_active=True)
    organization_ids = list(organizations.values_list("id", flat=True))
    organization_rows = []
    for organization in organizations.order_by("name"):
        usage_quantity = (
            UsageEvent.objects.filter(
                organization=organization,
                **_range_filter("created_at", date_range),
            ).aggregate(quantity=Sum("quantity"))["quantity"]
            or 0
        )
        documents_uploaded = Document.objects.filter(
            organization=organization,
            **_range_filter("created_at", date_range),
        ).count()
        if usage_quantity or documents_uploaded:
            organization_rows.append(
                {
                    "organization": organization,
                    "usage_quantity": usage_quantity,
                    "documents_uploaded": documents_uploaded,
                }
            )
    organization_rows.sort(key=lambda row: (row["usage_quantity"], row["documents_uploaded"]), reverse=True)

    return {
        "active_organizations": organizations.count(),
        "organizations_with_usage": UsageEvent.objects.filter(
            organization_id__in=organization_ids,
            **_range_filter("created_at", date_range),
        )
        .values("organization_id")
        .distinct()
        .count(),
        "documents_uploaded": Document.objects.filter(
            organization_id__in=organization_ids,
            **_range_filter("created_at", date_range),
        ).count(),
        "ai_documents_processed": ProcessingJob.objects.filter(
            organization_id__in=organization_ids,
            status=ProcessingJob.Status.COMPLETED,
            completed_at__gte=date_range["starts_at"],
            completed_at__lt=date_range["ends_at"],
        ).count(),
        "ai_fields_confirmed": ExtractedField.objects.filter(
            organization_id__in=organization_ids,
            status__in=[ExtractedField.Status.CONFIRMED, ExtractedField.Status.APPLIED],
            updated_at__gte=date_range["starts_at"],
            updated_at__lt=date_range["ends_at"],
        ).count(),
        "workflow_started": WorkflowInstance.objects.filter(
            organization_id__in=organization_ids,
            **_range_filter("started_at", date_range),
        ).count(),
        "workflow_completed": WorkflowInstance.objects.filter(
            organization_id__in=organization_ids,
            status__in=[
                WorkflowInstance.Status.APPROVED,
                WorkflowInstance.Status.REJECTED,
                WorkflowInstance.Status.CANCELED,
            ],
            completed_at__gte=date_range["starts_at"],
            completed_at__lt=date_range["ends_at"],
        ).count(),
        "documents_sent_to_counterparties": DocumentExchange.objects.filter(
            organization_id__in=organization_ids,
            direction=DocumentExchange.Direction.OUTGOING,
            **_range_filter("created_at", date_range),
        ).count(),
        "counterparties_created": Counterparty.objects.filter(
            organization_id__in=organization_ids,
            **_range_filter("created_at", date_range),
        ).count(),
        "evidence_exports": UsageEvent.objects.filter(
            organization_id__in=organization_ids,
            event_type=UsageEvent.EventType.EVIDENCE_EXPORTED,
            **_range_filter("created_at", date_range),
        ).aggregate(quantity=Sum("quantity"))["quantity"]
        or 0,
        "usage_summary": _usage_summary(organizations, date_range),
        "organization_rows": organization_rows[:20],
    }


def _avg_metric(organizations, *, name: str, category: str, date_range: dict[str, Any]) -> float:
    return (
        ObservabilityMetric.objects.filter(
            organization__in=organizations,
            name=name,
            category=category,
            **_range_filter("recorded_at", date_range),
        ).aggregate(avg=Avg("value"))["avg"]
        or 0
    )


def build_observability_summary(organizations, date_range: dict[str, Any]) -> dict[str, Any]:
    organizations = organizations.filter(is_active=True)
    for organization in organizations:
        record_queue_snapshot(organization=organization)
    evaluate_observability_alerts(organizations=organizations)

    jobs = ProcessingJob.objects.filter(organization__in=organizations)
    queue_by_status = {
        row["status"]: row["total"]
        for row in jobs.values("status").annotate(total=Count("id"))
    }
    failed_jobs = (
        jobs.filter(status=ProcessingJob.Status.FAILED)
        .select_related("organization", "document")
        .order_by("-completed_at", "-created_at")[:20]
    )
    slow_jobs = []
    for job in (
        jobs.filter(started_at__isnull=False)
        .select_related("organization", "document")
        .order_by("-started_at")[:100]
    ):
        end_at = job.completed_at or timezone.now()
        duration_seconds = (end_at - job.started_at).total_seconds()
        if duration_seconds >= 60:
            slow_jobs.append({"job": job, "duration_seconds": round(duration_seconds, 1)})
        if len(slow_jobs) >= 20:
            break

    stale_documents = DocumentSearchIndexState.objects.filter(
        organization__in=organizations,
        status__in=[DocumentSearchIndexState.Status.STALE, DocumentSearchIndexState.Status.FAILED],
    ).count()
    search_latency_avg = _avg_metric(
        organizations,
        name="search.latency_ms",
        category=ObservabilityMetric.Category.SEARCH,
        date_range=date_range,
    )
    embedding_latency_avg = _avg_metric(
        organizations,
        name="embedding.duration_ms",
        category=ObservabilityMetric.Category.PROCESSING,
        date_range=date_range,
    )
    qdrant_insert_avg = _avg_metric(
        organizations,
        name="qdrant.insert.duration_ms",
        category=ObservabilityMetric.Category.QDRANT,
        date_range=date_range,
    )
    processing_duration_avg = _avg_metric(
        organizations,
        name="job.duration_ms",
        category=ObservabilityMetric.Category.PROCESSING,
        date_range=date_range,
    )

    return {
        "queue_by_status": queue_by_status,
        "queue_pending": queue_by_status.get(ProcessingJob.Status.PENDING, 0),
        "queue_running": queue_by_status.get(ProcessingJob.Status.RUNNING, 0),
        "queue_failed": queue_by_status.get(ProcessingJob.Status.FAILED, 0),
        "avg_processing_time_ms": round(processing_duration_avg, 2),
        "avg_embedding_time_ms": round(embedding_latency_avg, 2),
        "avg_qdrant_insert_time_ms": round(qdrant_insert_avg, 2),
        "avg_search_latency_ms": round(search_latency_avg, 2),
        "failed_jobs": failed_jobs,
        "slow_jobs": slow_jobs,
        "stale_documents": stale_documents,
        "gpu": build_gpu_metrics_foundation(),
        "open_alerts": ObservabilityAlert.objects.filter(
            organization__in=organizations,
            status=ObservabilityAlert.Status.OPEN,
        ).order_by("-triggered_at")[:20],
        "recent_metrics": ObservabilityMetric.objects.filter(
            organization__in=organizations,
            **_range_filter("recorded_at", date_range),
        ).order_by("-recorded_at")[:30],
    }
