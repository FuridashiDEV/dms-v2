from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import connections
from django.db.models import Count, Q
from django.db.utils import OperationalError
from django.utils import timezone

from dms.models import ProcessingJob


@dataclass(frozen=True)
class RecoveryResult:
    job_id: int
    previous_status: str
    status: str
    action: str
    reason: str = ""


def get_stuck_processing_jobs(
    *,
    older_than_minutes: int | None = None,
    organization_id: int | None = None,
    stages: list[str] | None = None,
):
    cutoff = timezone.now() - timedelta(
        minutes=max(int(older_than_minutes or getattr(settings, "DMS_PROCESSING_STUCK_JOB_MINUTES", 30)), 1)
    )
    jobs = ProcessingJob.objects.filter(status=ProcessingJob.Status.RUNNING).filter(
        Q(locked_at__lte=cutoff) | Q(locked_at__isnull=True, started_at__lte=cutoff)
    )
    if organization_id is not None:
        jobs = jobs.filter(organization_id=organization_id)
    if stages:
        jobs = jobs.filter(pipeline_stage__in=stages)
    return jobs.order_by("locked_at", "started_at", "id")


def recover_stuck_processing_jobs(
    *,
    older_than_minutes: int | None = None,
    organization_id: int | None = None,
    stages: list[str] | None = None,
    dry_run: bool = False,
) -> list[RecoveryResult]:
    results: list[RecoveryResult] = []
    for job in get_stuck_processing_jobs(
        older_than_minutes=older_than_minutes,
        organization_id=organization_id,
        stages=stages,
    ):
        previous_status = job.status
        if job.can_retry:
            action = "retry"
            next_status = ProcessingJob.Status.PENDING
            reason = "stuck job returned to pending queue"
        else:
            action = "dead_letter"
            next_status = ProcessingJob.Status.DEAD_LETTER
            reason = "stuck job exceeded max attempts"

        if not dry_run:
            job.status = next_status
            job.locked_at = None
            job.lock_token = ""
            job.next_retry_at = timezone.now() if next_status == ProcessingJob.Status.PENDING else None
            job.completed_at = timezone.now() if next_status == ProcessingJob.Status.DEAD_LETTER else job.completed_at
            job.error_message = _append_recovery_note(job.error_message, reason)
            job.save(
                update_fields=[
                    "status",
                    "locked_at",
                    "lock_token",
                    "next_retry_at",
                    "completed_at",
                    "error_message",
                ]
            )
            _record_recovery_metric(job, action=action)

        results.append(
            RecoveryResult(
                job_id=job.id,
                previous_status=previous_status,
                status=next_status,
                action=action,
                reason=reason,
            )
        )
    return results


def restart_processing_job(
    job: ProcessingJob,
    *,
    reset_attempts: bool = True,
    reason: str = "manual restart",
) -> RecoveryResult:
    previous_status = job.status
    job.status = ProcessingJob.Status.PENDING
    job.locked_at = None
    job.lock_token = ""
    job.next_retry_at = timezone.now()
    job.completed_at = None
    job.error_message = _append_recovery_note(job.error_message, reason)
    update_fields = ["status", "locked_at", "lock_token", "next_retry_at", "completed_at", "error_message"]
    if reset_attempts:
        job.attempt_count = 0
        update_fields.append("attempt_count")
    job.save(update_fields=update_fields)
    _record_recovery_metric(job, action="manual_restart")
    return RecoveryResult(
        job_id=job.id,
        previous_status=previous_status,
        status=job.status,
        action="manual_restart",
        reason=reason,
    )


def mark_processing_job_dead_letter(job: ProcessingJob, *, reason: str = "manual dead letter") -> RecoveryResult:
    previous_status = job.status
    job.status = ProcessingJob.Status.DEAD_LETTER
    job.locked_at = None
    job.lock_token = ""
    job.next_retry_at = None
    job.completed_at = timezone.now()
    job.error_message = _append_recovery_note(job.error_message, reason)
    job.save(update_fields=["status", "locked_at", "lock_token", "next_retry_at", "completed_at", "error_message"])
    _record_recovery_metric(job, action="dead_letter")
    return RecoveryResult(
        job_id=job.id,
        previous_status=previous_status,
        status=job.status,
        action="dead_letter",
        reason=reason,
    )


def build_health_checks(*, include_qdrant: bool | None = None) -> tuple[dict[str, Any], int]:
    checks: dict[str, Any] = {}
    status_code = 200

    if getattr(settings, "HEALTH_CHECK_DATABASE", True):
        try:
            connections["default"].ensure_connection()
            checks["database"] = "ok"
        except OperationalError:
            checks["database"] = "error"
            status_code = 503

    if getattr(settings, "HEALTH_CHECK_STORAGE", True):
        storage_check = check_storage_available()
        checks["storage"] = storage_check
        if _check_status(storage_check) != "ok":
            status_code = 503

    if getattr(settings, "HEALTH_CHECK_QUEUE", True):
        queue_check = check_processing_queue_available()
        checks["queue"] = queue_check
        if _check_status(queue_check) != "ok":
            status_code = 503

    if getattr(settings, "HEALTH_CHECK_PROCESSING_WORKER", True):
        worker_check = check_processing_worker_foundation()
        checks["processing_worker"] = worker_check
        if _check_status(worker_check) != "ok":
            status_code = 503

    should_check_qdrant = getattr(settings, "HEALTH_CHECK_QDRANT", False) if include_qdrant is None else include_qdrant
    if should_check_qdrant:
        qdrant_check = check_qdrant_available()
        checks["qdrant"] = qdrant_check
        if _check_status(qdrant_check) != "ok":
            status_code = 503

    if not checks:
        checks["application"] = "ok"

    return checks, status_code


def check_storage_available() -> dict[str, Any]:
    try:
        media_root = Path(settings.MEDIA_ROOT)
        media_root.mkdir(parents=True, exist_ok=True)
        probe_path = media_root / ".dms-healthcheck"
        probe_path.write_text("ok", encoding="utf-8")
        probe_path.unlink(missing_ok=True)
        return {"status": "ok"}
    except Exception:
        return {"status": "error"}


def _check_status(value: Any) -> str:
    if isinstance(value, dict):
        return value.get("status", "error")
    return value


def check_processing_queue_available() -> dict[str, Any]:
    try:
        counts = dict(ProcessingJob.objects.values("status").annotate(count=Count("id")).values_list("status", "count"))
        return {
            "status": "ok",
            "pending": counts.get(ProcessingJob.Status.PENDING, 0),
            "running": counts.get(ProcessingJob.Status.RUNNING, 0),
            "failed": counts.get(ProcessingJob.Status.FAILED, 0),
            "dead_letter": counts.get(ProcessingJob.Status.DEAD_LETTER, 0),
        }
    except Exception:
        return {"status": "error"}


def check_processing_worker_foundation() -> dict[str, Any]:
    try:
        from dms.services.processing_roles import PROCESSING_ROLES

        return {
            "status": "ok",
            "roles": len(PROCESSING_ROLES),
            "mode": "foundation",
        }
    except Exception:
        return {"status": "error"}


def check_qdrant_available() -> dict[str, Any]:
    try:
        from dms.services.vector_store import ensure_collection

        return {"status": "ok" if ensure_collection() else "error"}
    except Exception:
        return {"status": "error"}


def _append_recovery_note(existing: str, note: str) -> str:
    timestamp = timezone.now().isoformat()
    recovery_note = f"[recovery {timestamp}] {note}"
    if not existing:
        return recovery_note
    return f"{existing[:3500]}\n{recovery_note}"[:4000]


def _record_recovery_metric(job: ProcessingJob, *, action: str) -> None:
    try:
        from dms.models import ObservabilityMetric
        from dms.services.observability import record_metric

        record_metric(
            organization=job.organization,
            category=ObservabilityMetric.Category.PROCESSING,
            name="processing.recovery.action",
            value=1,
            unit="count",
            labels={
                "action": action,
                "status": job.status,
                "pipeline_stage": job.pipeline_stage,
                "attempt_count": job.attempt_count,
            },
        )
    except Exception:
        pass
