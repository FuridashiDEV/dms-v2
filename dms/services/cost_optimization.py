from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import math
import os
from typing import Any

from django.db import transaction
from django.db.models import Count, Sum

from dms.models import (
    Document,
    Organization,
    ProcessingCostEstimate,
    ProcessingCostPolicy,
    ProcessingCostQuota,
    ProcessingJob,
    UsageEvent,
)
from dms.services.billing import current_month_range
from dms.services.embedding import get_embedding_model_name
from dms.services.usage import record_usage_event


LOW_TEXT_QUALITY_THRESHOLD = 0.35


@dataclass(frozen=True)
class OcrRoutingDecision:
    ocr_needed: bool
    reason: str
    text_quality: float


@dataclass(frozen=True)
class CostEstimateResult:
    document_count: int
    page_count: int
    ocr_needed: bool
    chunks_count: int
    embedding_model: str
    processing_time_ms: int
    estimated_cost_units: Decimal
    recommended_policy: str
    route_reason: str
    quota_snapshot: dict[str, Any]


DEFAULT_POLICY_DEFINITIONS = [
    ("immediate", "Immediate low-cost processing", ProcessingCostPolicy.PolicyType.IMMEDIATE, Decimal("8.00"), 0, True, True, 3, True),
    ("batch-30-min", "Batch within 30 minutes", ProcessingCostPolicy.PolicyType.BATCH_30_MIN, Decimal("30.00"), 30, True, True, 5, False),
    ("hourly", "Hourly cost-managed processing", ProcessingCostPolicy.PolicyType.HOURLY, Decimal("90.00"), 60, True, True, 7, False),
    ("nightly", "Nightly heavy processing", ProcessingCostPolicy.PolicyType.NIGHTLY, Decimal("999999.00"), 720, True, True, 9, False),
    ("manual", "Manual review before expensive processing", ProcessingCostPolicy.PolicyType.MANUAL, Decimal("0.00"), 0, False, False, 9, False),
    ("archive-only", "Archive only without expensive AI/OCR", ProcessingCostPolicy.PolicyType.ARCHIVE_ONLY, Decimal("0.00"), 0, False, False, 9, False),
    ("priority", "Priority processing override", ProcessingCostPolicy.PolicyType.PRIORITY, Decimal("999999.00"), 0, True, True, 1, False),
]


DEFAULT_QUOTA_DEFINITIONS = {
    ProcessingCostQuota.QuotaType.AI_DOCUMENTS: 2000,
    ProcessingCostQuota.QuotaType.OCR_PAGES: 5000,
    ProcessingCostQuota.QuotaType.EMBEDDINGS: 50000,
    ProcessingCostQuota.QuotaType.RERANK_REQUESTS: 10000,
    ProcessingCostQuota.QuotaType.COST_UNITS: 25000,
}


def ensure_default_cost_policies(organization: Organization | None = None) -> list[ProcessingCostPolicy]:
    policies = []
    for code, name, policy_type, max_cost, delay, ocr_allowed, gpu_allowed, priority, is_default in DEFAULT_POLICY_DEFINITIONS:
        policy, _created = ProcessingCostPolicy.objects.update_or_create(
            organization=organization,
            code=code,
            defaults={
                "name": name,
                "policy_type": policy_type,
                "max_cost_units": max_cost,
                "schedule_delay_minutes": delay,
                "ocr_allowed": ocr_allowed,
                "gpu_allowed": gpu_allowed,
                "priority": priority,
                "is_default": is_default,
                "is_active": True,
            },
        )
        policies.append(policy)
    return policies


def ensure_default_cost_quotas(organization: Organization) -> list[ProcessingCostQuota]:
    quotas = []
    for quota_type, limit in DEFAULT_QUOTA_DEFINITIONS.items():
        quota, _created = ProcessingCostQuota.objects.get_or_create(
            organization=organization,
            quota_type=quota_type,
            defaults={
                "monthly_limit": limit,
                "warning_percent": 80,
                "is_unlimited": False,
                "is_active": True,
            },
        )
        quotas.append(quota)
    return quotas


def should_run_ocr(document: Document, *, requested_ocr: bool = False) -> OcrRoutingDecision:
    if requested_ocr:
        return OcrRoutingDecision(True, "user_requested_ocr", _text_quality(document.extracted_text))

    text_quality = _text_quality(document.extracted_text)
    if not (document.extracted_text or "").strip():
        return OcrRoutingDecision(True, "no_extracted_text", text_quality)
    if text_quality < LOW_TEXT_QUALITY_THRESHOLD:
        return OcrRoutingDecision(True, "low_text_quality", text_quality)

    file_name = (document.source_file_name or getattr(document.file, "name", "") or "").lower()
    source_system = (document.source_system or "").lower()
    if any(marker in source_system for marker in ("scan", "scanned", "ocr_required")):
        return OcrRoutingDecision(True, "marked_as_scan", text_quality)
    if file_name.endswith((".tif", ".tiff", ".jpg", ".jpeg", ".png")) and len(document.extracted_text or "") < 200:
        return OcrRoutingDecision(True, "image_like_short_text", text_quality)

    return OcrRoutingDecision(False, "text_available", text_quality)


def estimate_document_processing_cost(
    document: Document,
    *,
    requested_ocr: bool = False,
    page_count: int | None = None,
    chunks_count: int | None = None,
    embedding_model: str | None = None,
    processing_time_ms: int = 0,
    priority: bool = False,
) -> CostEstimateResult:
    pages = max(int(page_count or _estimate_page_count(document)), 1)
    chunks = max(int(chunks_count or _estimate_chunks_count(document)), 1)
    embedding_model = embedding_model or get_embedding_model_name()
    ocr_decision = should_run_ocr(document, requested_ocr=requested_ocr)

    cost = Decimal("1.00")
    cost += Decimal(pages) * Decimal("0.40")
    if ocr_decision.ocr_needed:
        cost += Decimal(pages) * Decimal("2.50")
    cost += Decimal(chunks) * Decimal("0.15")
    if processing_time_ms:
        cost += Decimal(processing_time_ms) / Decimal("10000.00")
    if "large" in embedding_model.lower() or "bge-m3" in embedding_model.lower():
        cost += Decimal(chunks) * Decimal("0.10")
    cost = cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    policy = choose_processing_policy(
        organization=document.organization,
        estimated_cost_units=cost,
        priority=priority,
        ocr_needed=ocr_decision.ocr_needed,
    )
    quota_snapshot = build_cost_quota_snapshot(
        document.organization,
        projected={
            ProcessingCostQuota.QuotaType.AI_DOCUMENTS: 1,
            ProcessingCostQuota.QuotaType.OCR_PAGES: pages if ocr_decision.ocr_needed else 0,
            ProcessingCostQuota.QuotaType.EMBEDDINGS: chunks,
            ProcessingCostQuota.QuotaType.COST_UNITS: int(math.ceil(float(cost))),
        },
    )
    return CostEstimateResult(
        document_count=1,
        page_count=pages,
        ocr_needed=ocr_decision.ocr_needed,
        chunks_count=chunks,
        embedding_model=embedding_model,
        processing_time_ms=max(int(processing_time_ms or 0), 0),
        estimated_cost_units=cost,
        recommended_policy=policy.policy_type,
        route_reason=ocr_decision.reason,
        quota_snapshot=quota_snapshot,
    )


def choose_processing_policy(
    *,
    organization: Organization,
    estimated_cost_units: Decimal,
    priority: bool = False,
    ocr_needed: bool = False,
) -> ProcessingCostPolicy:
    policies = ensure_default_cost_policies(organization)
    if priority:
        return next(policy for policy in policies if policy.policy_type == ProcessingCostPolicy.PolicyType.PRIORITY)
    if not ocr_needed and estimated_cost_units <= Decimal("2.00"):
        archive_policy = next(policy for policy in policies if policy.policy_type == ProcessingCostPolicy.PolicyType.ARCHIVE_ONLY)
        return archive_policy
    active = [policy for policy in policies if policy.is_active and policy.max_cost_units > 0]
    active.sort(key=lambda policy: (policy.max_cost_units, policy.priority))
    for policy in active:
        if estimated_cost_units <= policy.max_cost_units:
            return policy
    return active[-1]


@transaction.atomic
def create_processing_cost_estimate(
    document: Document,
    *,
    processing_job: ProcessingJob | None = None,
    requested_ocr: bool = False,
    page_count: int | None = None,
    chunks_count: int | None = None,
    embedding_model: str | None = None,
    processing_time_ms: int = 0,
    priority: bool = False,
    record_usage: bool = True,
) -> ProcessingCostEstimate:
    result = estimate_document_processing_cost(
        document,
        requested_ocr=requested_ocr,
        page_count=page_count,
        chunks_count=chunks_count,
        embedding_model=embedding_model,
        processing_time_ms=processing_time_ms,
        priority=priority,
    )
    policy = ProcessingCostPolicy.objects.filter(
        organization=document.organization,
        policy_type=result.recommended_policy,
        is_active=True,
    ).order_by("max_cost_units", "priority").first()
    estimate = ProcessingCostEstimate.objects.create(
        organization=document.organization,
        document=document,
        processing_job=processing_job,
        policy=policy,
        document_count=result.document_count,
        page_count=result.page_count,
        ocr_needed=result.ocr_needed,
        chunks_count=result.chunks_count,
        embedding_model=result.embedding_model,
        processing_time_ms=result.processing_time_ms,
        estimated_cost_units=result.estimated_cost_units,
        recommended_policy=result.recommended_policy,
        route_reason=result.route_reason,
        quota_snapshot=result.quota_snapshot,
    )
    if record_usage:
        record_cost_usage_events(estimate)
    return estimate


def record_cost_usage_events(estimate: ProcessingCostEstimate) -> None:
    record_usage_event(
        event_type=UsageEvent.EventType.AI_DOCUMENT_PROCESSED,
        organization=estimate.organization,
        document=estimate.document,
        source="cost_optimization",
        quantity=estimate.document_count,
        metadata={"cost_estimate_id": estimate.id, "hard_enforcement": False},
    )
    if estimate.ocr_needed and estimate.page_count:
        record_usage_event(
            event_type=UsageEvent.EventType.OCR_PAGE_PROCESSED,
            organization=estimate.organization,
            document=estimate.document,
            source="cost_optimization",
            quantity=estimate.page_count,
            metadata={"cost_estimate_id": estimate.id},
        )
    if estimate.chunks_count:
        record_usage_event(
            event_type=UsageEvent.EventType.EMBEDDING_CHUNK_PROCESSED,
            organization=estimate.organization,
            document=estimate.document,
            source="cost_optimization",
            quantity=estimate.chunks_count,
            metadata={"cost_estimate_id": estimate.id, "embedding_model": estimate.embedding_model},
        )
    record_usage_event(
        event_type=UsageEvent.EventType.AI_COST_UNIT,
        organization=estimate.organization,
        document=estimate.document,
        source="cost_optimization",
        quantity=max(int(math.ceil(float(estimate.estimated_cost_units))), 1),
        metadata={"cost_estimate_id": estimate.id, "recommended_policy": estimate.recommended_policy},
    )


def build_cost_quota_snapshot(
    organization: Organization,
    *,
    projected: dict[str, int] | None = None,
    month: date | None = None,
) -> dict[str, Any]:
    ensure_default_cost_quotas(organization)
    starts_at, ends_at, period_start, period_end = current_month_range(month)
    usage_map = {
        UsageEvent.EventType.AI_DOCUMENT_PROCESSED: ProcessingCostQuota.QuotaType.AI_DOCUMENTS,
        UsageEvent.EventType.OCR_PAGE_PROCESSED: ProcessingCostQuota.QuotaType.OCR_PAGES,
        UsageEvent.EventType.EMBEDDING_CHUNK_PROCESSED: ProcessingCostQuota.QuotaType.EMBEDDINGS,
        UsageEvent.EventType.RERANK_REQUEST: ProcessingCostQuota.QuotaType.RERANK_REQUESTS,
        UsageEvent.EventType.AI_COST_UNIT: ProcessingCostQuota.QuotaType.COST_UNITS,
    }
    usage_rows = (
        UsageEvent.objects.filter(
            organization=organization,
            event_type__in=list(usage_map),
            created_at__gte=starts_at,
            created_at__lt=ends_at,
        )
        .values("event_type")
        .annotate(total=Sum("quantity"))
    )
    used_by_quota = {quota_type: 0 for quota_type in ProcessingCostQuota.QuotaType.values}
    for row in usage_rows:
        quota_type = usage_map.get(row["event_type"])
        if quota_type:
            used_by_quota[quota_type] = int(row["total"] or 0)

    projected = projected or {}
    rows = []
    for quota in ProcessingCostQuota.objects.filter(organization=organization, is_active=True).order_by("quota_type"):
        used = used_by_quota.get(quota.quota_type, 0)
        projected_units = int(projected.get(quota.quota_type, 0) or 0)
        projected_total = used + projected_units
        if quota.is_unlimited:
            percent_used = None
            warning_level = "unlimited"
            remaining = None
        else:
            limit = max(quota.monthly_limit, 0)
            percent_used = 100 if limit == 0 and projected_total else round((projected_total / max(limit, 1)) * 100, 2)
            remaining = max(limit - projected_total, 0)
            if percent_used >= 100:
                warning_level = "exceeded"
            elif percent_used >= quota.warning_percent:
                warning_level = "warning"
            else:
                warning_level = "ok"
        rows.append(
            {
                "quota_type": quota.quota_type,
                "used": used,
                "projected": projected_units,
                "projected_total": projected_total,
                "limit": None if quota.is_unlimited else quota.monthly_limit,
                "remaining": remaining,
                "percent_used": percent_used,
                "warning_level": warning_level,
                "hard_enforcement": False,
            }
        )
    return {
        "organization_id": organization.id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "rows": rows,
        "hard_enforcement": False,
    }


def build_cost_dashboard_report(organization: Organization, *, month: date | None = None) -> dict[str, Any]:
    starts_at, ends_at, period_start, period_end = current_month_range(month)
    ensure_default_cost_policies(organization)
    ensure_default_cost_quotas(organization)
    estimates = ProcessingCostEstimate.objects.filter(
        organization=organization,
        created_at__gte=starts_at,
        created_at__lt=ends_at,
    )
    summary = estimates.aggregate(
        total_cost_units=Sum("estimated_cost_units"),
        total_documents=Sum("document_count"),
        total_pages=Sum("page_count"),
        total_chunks=Sum("chunks_count"),
    )
    by_policy = list(
        estimates.values("recommended_policy")
        .annotate(
            count=Count("id"),
            cost_units=Sum("estimated_cost_units"),
            pages=Sum("page_count"),
            chunks=Sum("chunks_count"),
        )
        .order_by("recommended_policy")
    )
    backlog = (
        ProcessingJob.objects.filter(organization=organization, status=ProcessingJob.Status.PENDING)
        .select_related("document")
        .order_by("-created_at")[:25]
    )
    backlog_rows = []
    for job in backlog:
        latest_estimate = job.cost_estimates.order_by("-created_at").first()
        backlog_rows.append(
            {
                "job": job,
                "document": job.document,
                "pipeline_stage": job.pipeline_stage,
                "policy": latest_estimate.recommended_policy if latest_estimate else "",
                "estimated_cost_units": latest_estimate.estimated_cost_units if latest_estimate else Decimal("0.00"),
            }
        )
    return {
        "organization": organization,
        "period_start": period_start,
        "period_end": period_end,
        "total_cost_units": summary["total_cost_units"] or Decimal("0.00"),
        "total_documents": summary["total_documents"] or 0,
        "total_pages": summary["total_pages"] or 0,
        "total_chunks": summary["total_chunks"] or 0,
        "ocr_pages": estimates.filter(ocr_needed=True).aggregate(total=Sum("page_count"))["total"] or 0,
        "by_policy": by_policy,
        "quota_snapshot": build_cost_quota_snapshot(organization, month=month),
        "policies": ProcessingCostPolicy.objects.filter(organization=organization, is_active=True).order_by("max_cost_units", "priority"),
        "heavy_estimates": estimates.select_related("document", "policy").order_by("-estimated_cost_units", "-created_at")[:20],
        "backlog_by_cost": backlog_rows,
        "hard_enforcement": False,
    }


def _text_quality(text: str) -> float:
    text = text or ""
    if not text.strip():
        return 0.0
    alnum = sum(1 for char in text if char.isalnum())
    visible = sum(1 for char in text if not char.isspace())
    if not visible:
        return 0.0
    return round(min(alnum / visible, 1.0), 4)


def _estimate_page_count(document: Document) -> int:
    metadata_pages = (document.search_entities or {}).get("page_count") if isinstance(document.search_entities, dict) else None
    if metadata_pages:
        return max(int(metadata_pages), 1)
    try:
        file_size = document.file.size if document.file else 0
    except Exception:
        file_size = 0
    if file_size:
        return max(math.ceil(file_size / 120_000), 1)
    text_length = len(document.extracted_text or document.description or document.title or "")
    return max(math.ceil(text_length / 2500), 1)


def _estimate_chunks_count(document: Document) -> int:
    text_length = len(document.search_text_normalized or document.extracted_text or document.description or document.title or "")
    return max(math.ceil(text_length / 1200), 1)
