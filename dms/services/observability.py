from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db.models import Avg, Count, Q
from django.utils import timezone

from dms.models import (
    DocumentSearchIndexState,
    ObservabilityAlert,
    ObservabilityMetric,
    Organization,
    ProcessingJob,
)


SENSITIVE_KEY_PARTS = ("token", "secret", "password", "api_key", "apikey", "private_key", "authorization", "payload")


def sanitize_observability_labels(value: Any) -> Any:
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
                continue
            safe[str(key)[:80]] = sanitize_observability_labels(item)
        return safe
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_observability_labels(item) for item in list(value)[:20]]
    if isinstance(value, str):
        return value[:256]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:256]


def record_metric(
    *,
    name: str,
    category: str,
    value: float,
    organization: Organization | None = None,
    unit: str = "",
    labels: dict[str, Any] | None = None,
) -> ObservabilityMetric:
    return ObservabilityMetric.objects.create(
        organization=organization,
        category=category,
        name=name[:120],
        value=float(value or 0),
        unit=unit[:40],
        labels=sanitize_observability_labels(labels or {}),
    )


@contextmanager
def observe_duration(
    *,
    name: str,
    category: str,
    organization: Organization | None = None,
    unit: str = "ms",
    labels: dict[str, Any] | None = None,
):
    started = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        record_metric(
            name=name,
            category=category,
            value=round(duration_ms, 3),
            organization=organization,
            unit=unit,
            labels=labels,
        )


def record_processing_job_metric(job: ProcessingJob, *, event: str) -> None:
    labels = {
        "event": event,
        "status": job.status,
        "pipeline_stage": job.pipeline_stage,
        "source": job.source,
        "attempt_count": job.attempt_count,
    }
    if job.started_at and job.completed_at:
        duration_ms = (job.completed_at - job.started_at).total_seconds() * 1000
        record_metric(
            name="job.duration_ms",
            category=ObservabilityMetric.Category.PROCESSING,
            value=round(duration_ms, 3),
            organization=job.organization,
            unit="ms",
            labels=labels,
        )
    record_metric(
        name=f"job.{event}",
        category=ObservabilityMetric.Category.PROCESSING,
        value=1,
        organization=job.organization,
        unit="count",
        labels=labels,
    )


def record_queue_snapshot(*, organization: Organization | None = None) -> list[ObservabilityMetric]:
    jobs = ProcessingJob.objects.all()
    if organization is not None:
        jobs = jobs.filter(organization=organization)

    counts = dict(jobs.values("status").annotate(total=Count("id")).values_list("status", "total"))
    metrics = []
    for status in ProcessingJob.Status.values:
        metrics.append(
            record_metric(
                name=f"queue.{status.lower()}",
                category=ObservabilityMetric.Category.QUEUE,
                value=counts.get(status, 0),
                organization=organization,
                unit="count",
                labels={"status": status},
            )
        )
    return metrics


def record_search_latency(
    *,
    organization_ids: list[int] | None,
    latency_ms: float,
    degraded: bool,
    result_count: int = 0,
    source: str = "qdrant",
) -> list[ObservabilityMetric]:
    labels = {
        "degraded": degraded,
        "source": source,
        "result_count": result_count,
    }
    organizations = Organization.objects.filter(id__in=organization_ids or [])
    if not organization_ids:
        return [
            record_metric(
                name="search.latency_ms",
                category=ObservabilityMetric.Category.SEARCH,
                value=round(latency_ms, 3),
                unit="ms",
                labels=labels,
            )
        ]
    return [
        record_metric(
            name="search.latency_ms",
            category=ObservabilityMetric.Category.SEARCH,
            value=round(latency_ms, 3),
            organization=organization,
            unit="ms",
            labels=labels,
        )
        for organization in organizations
    ]


def record_qdrant_availability(*, available: bool) -> ObservabilityMetric:
    return record_metric(
        name="qdrant.available",
        category=ObservabilityMetric.Category.QDRANT,
        value=1 if available else 0,
        unit="bool",
        labels={"available": available},
    )


def build_gpu_metrics_foundation() -> dict[str, Any]:
    recent_gpu_metrics = ObservabilityMetric.objects.filter(
        category=ObservabilityMetric.Category.GPU,
        recorded_at__gte=timezone.now() - timedelta(hours=24),
    )
    return {
        "gpu_available": getattr(settings, "DMS_GPU_AVAILABLE", False),
        "gpu_busy": bool(recent_gpu_metrics.filter(name="gpu.busy", value__gt=0).exists()),
        "worker_count": ProcessingJob.objects.filter(
            status=ProcessingJob.Status.RUNNING,
            pipeline_stage__in=[ProcessingJob.Stage.EMBEDDING, ProcessingJob.Stage.RERANKING],
        ).count(),
        "batch_size": recent_gpu_metrics.filter(name="gpu.batch_size").aggregate(avg=Avg("value"))["avg"] or 0,
        "avg_batch_duration_ms": recent_gpu_metrics.filter(name="gpu.batch.duration_ms").aggregate(avg=Avg("value"))["avg"]
        or 0,
    }


def create_or_update_alert(
    *,
    alert_type: str,
    title: str,
    severity: str = ObservabilityAlert.Severity.WARNING,
    organization: Organization | None = None,
    details: dict[str, Any] | None = None,
) -> ObservabilityAlert:
    alert, _created = ObservabilityAlert.objects.update_or_create(
        organization=organization,
        alert_type=alert_type[:120],
        status=ObservabilityAlert.Status.OPEN,
        defaults={
            "title": title[:255],
            "severity": severity,
            "details": sanitize_observability_labels(details or {}),
        },
    )
    return alert


def evaluate_observability_alerts(*, organizations=None) -> list[ObservabilityAlert]:
    organizations = organizations or Organization.objects.filter(is_active=True)
    alerts: list[ObservabilityAlert] = []
    failed_threshold = getattr(settings, "DMS_OBSERVABILITY_FAILED_JOBS_THRESHOLD", 5)
    pending_threshold = getattr(settings, "DMS_OBSERVABILITY_QUEUE_PENDING_THRESHOLD", 50)
    latency_threshold = getattr(settings, "DMS_OBSERVABILITY_SEARCH_LATENCY_MS_THRESHOLD", 2000)
    stale_threshold = getattr(settings, "DMS_OBSERVABILITY_STALE_DOCUMENTS_THRESHOLD", 10)
    since = timezone.now() - timedelta(hours=24)

    for organization in organizations:
        failed_count = ProcessingJob.objects.filter(
            organization=organization,
            status=ProcessingJob.Status.FAILED,
        ).filter(Q(completed_at__gte=since) | Q(created_at__gte=since)).count()
        if failed_count >= failed_threshold:
            alerts.append(
                create_or_update_alert(
                    organization=organization,
                    alert_type="processing.failed_jobs_high",
                    title="Processing failed jobs threshold exceeded",
                    severity=ObservabilityAlert.Severity.WARNING,
                    details={"failed_jobs": failed_count, "threshold": failed_threshold},
                )
            )

        pending_count = ProcessingJob.objects.filter(
            organization=organization,
            status=ProcessingJob.Status.PENDING,
        ).count()
        if pending_count >= pending_threshold:
            alerts.append(
                create_or_update_alert(
                    organization=organization,
                    alert_type="processing.queue_pending_high",
                    title="Processing queue pending threshold exceeded",
                    severity=ObservabilityAlert.Severity.WARNING,
                    details={"pending_jobs": pending_count, "threshold": pending_threshold},
                )
            )

        avg_latency = (
            ObservabilityMetric.objects.filter(
                organization=organization,
                category=ObservabilityMetric.Category.SEARCH,
                name="search.latency_ms",
                recorded_at__gte=since,
            ).aggregate(avg=Avg("value"))["avg"]
            or 0
        )
        if avg_latency >= latency_threshold:
            alerts.append(
                create_or_update_alert(
                    organization=organization,
                    alert_type="search.latency_high",
                    title="Search latency threshold exceeded",
                    severity=ObservabilityAlert.Severity.WARNING,
                    details={"avg_latency_ms": round(avg_latency, 3), "threshold": latency_threshold},
                )
            )

        stale_count = DocumentSearchIndexState.objects.filter(
            organization=organization,
            status__in=[DocumentSearchIndexState.Status.STALE, DocumentSearchIndexState.Status.FAILED],
        ).count()
        if stale_count >= stale_threshold:
            alerts.append(
                create_or_update_alert(
                    organization=organization,
                    alert_type="search.stale_documents_high",
                    title="Stale search index documents threshold exceeded",
                    severity=ObservabilityAlert.Severity.WARNING,
                    details={"stale_documents": stale_count, "threshold": stale_threshold},
                )
            )

    unavailable_qdrant = ObservabilityMetric.objects.filter(
        category=ObservabilityMetric.Category.QDRANT,
        name="qdrant.available",
        value=0,
        recorded_at__gte=since,
    ).exists()
    if unavailable_qdrant:
        alerts.append(
            create_or_update_alert(
                alert_type="qdrant.unavailable",
                title="Qdrant availability check failed",
                severity=ObservabilityAlert.Severity.CRITICAL,
                details={"window_hours": 24},
            )
        )

    return alerts
