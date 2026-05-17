from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from dms.models import Document, Organization, ProcessingJob, ProcessingProfile


DEFAULT_PROFILE_CODE = "default-ai-processing"
DEFAULT_PROFILE_NAME = "Default AI Processing"


@dataclass(frozen=True)
class BackpressureState:
    available: bool
    queued_count: int
    running_count: int
    max_concurrent_jobs: int
    reason: str = ""


@dataclass(frozen=True)
class DispatchResult:
    job: ProcessingJob
    executed: bool
    status: str
    reason: str = ""


JobHandler = Callable[[ProcessingJob], dict[str, Any] | None]


def default_processing_stages() -> list[str]:
    return [stage for stage, _label in ProcessingJob.Stage.choices]


def get_or_create_default_processing_profile(
    organization: Organization | None = None,
) -> ProcessingProfile:
    profile, _created = ProcessingProfile.objects.get_or_create(
        organization=organization,
        code=DEFAULT_PROFILE_CODE,
        defaults={
            "name": DEFAULT_PROFILE_NAME,
            "description": "Default local foundation profile for staged AI processing.",
            "max_concurrent_jobs": 2,
            "max_attempts": 3,
            "retry_backoff_seconds": 300,
            "allowed_stages": default_processing_stages(),
        },
    )
    return profile


def build_processing_payload_snapshot(document: Document) -> dict[str, Any]:
    return {
        "document": {
            "id": document.id,
            "public_id": str(document.public_id) if document.public_id else "",
            "title": document.title,
            "status": document.status,
            "checksum_sha256": document.checksum_sha256,
            "extracted_text_length": len(document.extracted_text or ""),
            "has_file": bool(document.file),
        },
        "organization": {
            "id": document.organization_id,
            "name": document.organization.name,
        },
    }


def _resolve_profile(document: Document, profile: ProcessingProfile | None) -> ProcessingProfile:
    if profile is not None:
        return profile
    return get_or_create_default_processing_profile(document.organization)


def get_backpressure_state(
    *,
    profile: ProcessingProfile,
    organization: Organization | None = None,
) -> BackpressureState:
    organization = organization or profile.organization
    jobs = ProcessingJob.objects.filter(profile=profile)
    if organization is not None:
        jobs = jobs.filter(organization=organization)

    queued_count = jobs.filter(status=ProcessingJob.Status.PENDING).count()
    running_count = jobs.filter(status=ProcessingJob.Status.RUNNING).count()
    max_concurrent_jobs = max(profile.max_concurrent_jobs, 1)
    available = profile.is_active and running_count < max_concurrent_jobs

    reason = ""
    if not profile.is_active:
        reason = "profile_inactive"
    elif not available:
        reason = "max_concurrent_jobs_reached"

    return BackpressureState(
        available=available,
        queued_count=queued_count,
        running_count=running_count,
        max_concurrent_jobs=max_concurrent_jobs,
        reason=reason,
    )


def enqueue_processing_job(
    *,
    document: Document,
    stage: str = ProcessingJob.Stage.AI_PARSE,
    source: str = ProcessingJob.Source.MANUAL,
    user=None,
    profile: ProcessingProfile | None = None,
    parent_job: ProcessingJob | None = None,
    idempotency_key: str = "",
    payload: dict[str, Any] | None = None,
    scheduled_at=None,
    priority: int = 5,
) -> ProcessingJob:
    profile = _resolve_profile(document, profile)
    if profile.organization_id not in (None, document.organization_id):
        raise ValueError("Processing profile organization must match document organization or be global.")
    if parent_job is not None and parent_job.organization_id != document.organization_id:
        raise ValueError("Parent processing job organization must match document organization.")

    if stage not in default_processing_stages():
        raise ValueError(f"Unsupported processing stage: {stage}")
    if profile.allowed_stages and stage not in profile.allowed_stages:
        raise ValueError(f"Processing stage {stage} is not allowed by profile {profile.code}.")

    if idempotency_key:
        existing = ProcessingJob.objects.filter(
            organization=document.organization,
            document=document,
            pipeline_stage=stage,
            idempotency_key=idempotency_key,
        ).order_by("-created_at").first()
        if existing is not None:
            return existing

    center_metadata = build_processing_payload_snapshot(document)
    if payload:
        center_metadata["payload"] = payload

    job = ProcessingJob.objects.create(
        organization=document.organization,
        document=document,
        created_by=user if getattr(user, "is_authenticated", False) else None,
        profile=profile,
        parent_job=parent_job,
        status=ProcessingJob.Status.PENDING,
        source=source,
        pipeline_stage=stage,
        priority=max(int(priority or 5), 1),
        max_attempts=max(profile.max_attempts, 1),
        scheduled_at=scheduled_at or timezone.now(),
        idempotency_key=idempotency_key[:120],
        center_metadata=center_metadata,
    )
    _record_processing_event("processing.job_queued", job, user=user)
    return job


def fan_out_processing_job(
    *,
    parent_job: ProcessingJob,
    stages: Iterable[str],
    user=None,
    priority: int | None = None,
) -> list[ProcessingJob]:
    child_jobs = []
    for stage in stages:
        child_jobs.append(
            enqueue_processing_job(
                document=parent_job.document,
                stage=stage,
                source=parent_job.source,
                user=user,
                profile=parent_job.profile,
                parent_job=parent_job,
                idempotency_key=f"{parent_job.id}:{stage}",
                priority=priority if priority is not None else parent_job.priority,
            )
        )
    parent_job.pipeline_stage = ProcessingJob.Stage.FAN_OUT
    parent_job.center_metadata = {
        **(parent_job.center_metadata or {}),
        "fan_out_child_job_ids": [job.id for job in child_jobs],
    }
    parent_job.save(update_fields=["pipeline_stage", "center_metadata"])
    _record_processing_event(
        "processing.fan_out_created",
        parent_job,
        user=user,
        metadata={"child_job_ids": [job.id for job in child_jobs]},
    )
    return child_jobs


def fan_in_processing_job(parent_job: ProcessingJob, *, user=None) -> ProcessingJob:
    children = parent_job.child_jobs.all()
    if not children.exists():
        return parent_job

    active_statuses = [ProcessingJob.Status.PENDING, ProcessingJob.Status.RUNNING]
    if children.filter(status__in=active_statuses).exists():
        return parent_job

    now = timezone.now()
    if children.filter(status=ProcessingJob.Status.FAILED).exists():
        parent_job.status = ProcessingJob.Status.FAILED
        parent_job.error_message = "One or more child processing jobs failed."
    else:
        parent_job.status = ProcessingJob.Status.COMPLETED
        parent_job.error_message = ""
        parent_job.raw_result = {
            **(parent_job.raw_result or {}),
            "child_job_ids": list(children.values_list("id", flat=True)),
        }
    parent_job.pipeline_stage = ProcessingJob.Stage.FAN_IN
    parent_job.completed_at = now
    parent_job.locked_at = None
    parent_job.lock_token = ""
    parent_job.save(
        update_fields=[
            "status",
            "pipeline_stage",
            "raw_result",
            "error_message",
            "completed_at",
            "locked_at",
            "lock_token",
        ]
    )
    _record_processing_event("processing.fan_in_completed", parent_job, user=user)
    return parent_job


def claim_next_processing_job(
    *,
    profile: ProcessingProfile | None = None,
    organization: Organization | None = None,
    stages: Iterable[str] | None = None,
    lock_token: str | None = None,
    now=None,
) -> ProcessingJob | None:
    now = now or timezone.now()
    if profile is not None:
        backpressure = get_backpressure_state(profile=profile, organization=organization)
        if not backpressure.available:
            return None

    with transaction.atomic():
        jobs = ProcessingJob.objects.select_for_update().filter(
            status=ProcessingJob.Status.PENDING,
            scheduled_at__lte=now,
        ).filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))
        if profile is not None:
            jobs = jobs.filter(profile=profile)
        if organization is not None:
            jobs = jobs.filter(organization=organization)
        if stages is not None:
            jobs = jobs.filter(pipeline_stage__in=list(stages))

        job = None
        for candidate in jobs.order_by("priority", "created_at", "id")[:25]:
            if candidate.profile_id is None:
                job = candidate
                break
            candidate_backpressure = get_backpressure_state(
                profile=candidate.profile,
                organization=candidate.organization,
            )
            if candidate_backpressure.available:
                job = candidate
                break
        if job is None:
            return None

        job.status = ProcessingJob.Status.RUNNING
        job.started_at = job.started_at or now
        job.locked_at = now
        job.lock_token = lock_token or uuid.uuid4().hex
        job.attempt_count += 1
        job.save(update_fields=["status", "started_at", "locked_at", "lock_token", "attempt_count"])
        return job


def complete_processing_job(
    job: ProcessingJob,
    *,
    result: dict[str, Any] | None = None,
    user=None,
) -> ProcessingJob:
    job.status = ProcessingJob.Status.COMPLETED
    job.raw_result = result or {}
    job.error_message = ""
    job.completed_at = timezone.now()
    job.locked_at = None
    job.lock_token = ""
    job.next_retry_at = None
    job.save(
        update_fields=[
            "status",
            "raw_result",
            "error_message",
            "completed_at",
            "locked_at",
            "lock_token",
            "next_retry_at",
        ]
    )
    _record_processing_event("processing.job_completed", job, user=user)
    try:
        from dms.services.observability import record_processing_job_metric

        record_processing_job_metric(job, event="completed")
    except Exception:
        pass
    if job.parent_job_id:
        fan_in_processing_job(job.parent_job, user=user)
    return job


def fail_processing_job(
    job: ProcessingJob,
    *,
    error_message: str,
    user=None,
) -> ProcessingJob:
    profile = job.profile or get_or_create_default_processing_profile(job.organization)
    now = timezone.now()
    job.error_message = (error_message or "Processing job failed.")[:4000]
    job.locked_at = None
    job.lock_token = ""

    if job.can_retry:
        backoff = max(profile.retry_backoff_seconds, 1) * max(job.attempt_count, 1)
        job.status = ProcessingJob.Status.PENDING
        job.next_retry_at = now + timedelta(seconds=backoff)
        update_fields = ["status", "error_message", "locked_at", "lock_token", "next_retry_at"]
        event_type = "processing.job_retry_scheduled"
    else:
        job.status = ProcessingJob.Status.FAILED
        job.completed_at = now
        update_fields = ["status", "error_message", "locked_at", "lock_token", "completed_at"]
        event_type = "processing.job_failed"

    job.save(update_fields=update_fields)
    _record_processing_event(event_type, job, user=user, metadata={"attempt_count": job.attempt_count})
    try:
        from dms.services.observability import record_processing_job_metric

        record_processing_job_metric(job, event="retry_scheduled" if job.status == ProcessingJob.Status.PENDING else "failed")
    except Exception:
        pass
    if job.parent_job_id and job.status == ProcessingJob.Status.FAILED:
        fan_in_processing_job(job.parent_job, user=user)
    return job


def default_processing_handlers() -> dict[str, JobHandler]:
    return {
        ProcessingJob.Stage.AI_PARSE: _noop_foundation_handler,
        ProcessingJob.Stage.OCR: _noop_foundation_handler,
        ProcessingJob.Stage.TEXT_EXTRACTION: _noop_foundation_handler,
        ProcessingJob.Stage.ENTITY_EXTRACTION: _noop_foundation_handler,
        ProcessingJob.Stage.CHUNKING: _noop_foundation_handler,
        ProcessingJob.Stage.EMBEDDING: _reindex_handler,
        ProcessingJob.Stage.RERANKING: _noop_foundation_handler,
        ProcessingJob.Stage.REINDEX: _reindex_handler,
        ProcessingJob.Stage.FAN_OUT: _noop_foundation_handler,
        ProcessingJob.Stage.FAN_IN: _noop_foundation_handler,
    }


def execute_processing_job(
    job: ProcessingJob,
    *,
    handlers: dict[str, JobHandler] | None = None,
    user=None,
) -> DispatchResult:
    handlers = {**default_processing_handlers(), **(handlers or {})}
    handler = handlers.get(job.pipeline_stage)
    if handler is None:
        fail_processing_job(job, error_message=f"No handler for stage {job.pipeline_stage}.", user=user)
        return DispatchResult(job=job, executed=False, status=job.status, reason="missing_handler")

    try:
        result = handler(job) or {}
    except Exception as exc:
        fail_processing_job(job, error_message=str(exc), user=user)
        return DispatchResult(job=job, executed=True, status=job.status, reason="handler_failed")

    complete_processing_job(job, result=result, user=user)
    return DispatchResult(job=job, executed=True, status=job.status)


def drain_processing_queue(
    *,
    limit: int = 10,
    profile: ProcessingProfile | None = None,
    organization: Organization | None = None,
    stages: Iterable[str] | None = None,
    handlers: dict[str, JobHandler] | None = None,
    user=None,
) -> list[DispatchResult]:
    results: list[DispatchResult] = []
    for _index in range(max(int(limit or 0), 0)):
        job = claim_next_processing_job(profile=profile, organization=organization, stages=stages)
        if job is None:
            break
        results.append(execute_processing_job(job, handlers=handlers, user=user))
    return results


def _noop_foundation_handler(job: ProcessingJob) -> dict[str, Any]:
    return {
        "foundation_only": True,
        "stage": job.pipeline_stage,
        "note": "No remote processing center is connected; current synchronous flows remain unchanged.",
    }


def _reindex_handler(job: ProcessingJob) -> dict[str, Any]:
    from dms.services.document_indexing import index_document

    index_document(job.document)
    return {"indexed_document_id": job.document_id}


def _record_processing_event(
    event_type: str,
    job: ProcessingJob,
    *,
    user=None,
    metadata: dict[str, Any] | None = None,
) -> None:
    event_metadata = {
        "processing_job_id": job.id,
        "processing_profile_id": job.profile_id,
        "pipeline_stage": job.pipeline_stage,
        "status": job.status,
    }
    if metadata:
        event_metadata.update(metadata)
    try:
        from dms.services.audit import record_audit_event

        record_audit_event(
            event_type=event_type,
            user=user,
            document=job.document,
            organization=job.organization,
            metadata=event_metadata,
        )
    except Exception:
        pass
    try:
        from dms.services.usage import record_usage_event

        record_usage_event(
            event_type=event_type,
            organization=job.organization,
            user=user,
            document=job.document,
            source="processing_center",
            metadata=event_metadata,
        )
    except Exception:
        pass
