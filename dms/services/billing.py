from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from dms.models import AuditEvent, Organization, Plan, PlanQuota, Subscription, UsageEvent
from dms.services.audit import record_audit_event


DEFAULT_PLAN_CODE = "free"


BASE_PLAN_DEFINITIONS = [
    {
        "code": "free",
        "name": "Free",
        "description": "Default internal foundation plan. Report-only quotas, no billing enforcement.",
        "billing_interval": Plan.BillingInterval.MANUAL,
        "price_amount": Decimal("0.00"),
        "currency": "KZT",
        "quotas": {
            UsageEvent.EventType.DOCUMENT_UPLOADED: 100,
            UsageEvent.EventType.IMPORT_FILE_IMPORTED: 100,
            UsageEvent.EventType.AI_PROCESSING_STARTED: 50,
            UsageEvent.EventType.WORKFLOW_ACTION: 100,
            UsageEvent.EventType.EXCHANGE_EVENT: 50,
            UsageEvent.EventType.EVIDENCE_EXPORTED: 20,
            UsageEvent.EventType.EXTERNAL_REFERENCE_LINKED: 100,
        },
    },
    {
        "code": "team",
        "name": "Team",
        "description": "Internal growth plan placeholder. Report-only quotas, no billing enforcement.",
        "billing_interval": Plan.BillingInterval.MANUAL,
        "price_amount": Decimal("0.00"),
        "currency": "KZT",
        "quotas": {
            UsageEvent.EventType.DOCUMENT_UPLOADED: 5000,
            UsageEvent.EventType.IMPORT_FILE_IMPORTED: 5000,
            UsageEvent.EventType.AI_PROCESSING_STARTED: 2000,
            UsageEvent.EventType.WORKFLOW_ACTION: 3000,
            UsageEvent.EventType.EXCHANGE_EVENT: 1000,
            UsageEvent.EventType.EVIDENCE_EXPORTED: 500,
            UsageEvent.EventType.EXTERNAL_REFERENCE_LINKED: 5000,
        },
    },
    {
        "code": "enterprise",
        "name": "Enterprise",
        "description": "Internal enterprise placeholder. Unlimited report-only quotas, no billing enforcement.",
        "billing_interval": Plan.BillingInterval.MANUAL,
        "price_amount": Decimal("0.00"),
        "currency": "KZT",
        "quotas": {
            UsageEvent.EventType.DOCUMENT_UPLOADED: None,
            UsageEvent.EventType.IMPORT_FILE_IMPORTED: None,
            UsageEvent.EventType.AI_PROCESSING_STARTED: None,
            UsageEvent.EventType.WORKFLOW_ACTION: None,
            UsageEvent.EventType.EXCHANGE_EVENT: None,
            UsageEvent.EventType.EVIDENCE_EXPORTED: None,
            UsageEvent.EventType.EXTERNAL_REFERENCE_LINKED: None,
        },
    },
]


def _first_day_of_next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def current_month_range(month: date | None = None) -> tuple[datetime, datetime, date, date]:
    month_start = (month or timezone.localdate()).replace(day=1)
    month_end = _first_day_of_next_month(month_start)
    current_tz = timezone.get_current_timezone()
    starts_at = timezone.make_aware(datetime.combine(month_start, time.min), current_tz)
    ends_at = timezone.make_aware(datetime.combine(month_end, time.min), current_tz)
    return starts_at, ends_at, month_start, month_end


@transaction.atomic
def seed_base_plans() -> list[Plan]:
    plans: list[Plan] = []
    for plan_data in BASE_PLAN_DEFINITIONS:
        quotas = plan_data["quotas"]
        plan, _ = Plan.objects.update_or_create(
            code=plan_data["code"],
            defaults={
                "name": plan_data["name"],
                "description": plan_data["description"],
                "billing_interval": plan_data["billing_interval"],
                "price_amount": plan_data["price_amount"],
                "currency": plan_data["currency"],
                "is_active": True,
            },
        )
        for usage_event_type, limit in quotas.items():
            PlanQuota.objects.update_or_create(
                plan=plan,
                usage_event_type=usage_event_type,
                defaults={
                    "limit": 0 if limit is None else int(limit),
                    "is_unlimited": limit is None,
                },
            )
        plans.append(plan)
    return plans


def get_default_plan() -> Plan:
    return Plan.objects.get(code=DEFAULT_PLAN_CODE)


@transaction.atomic
def ensure_default_subscription(
    organization: Organization,
    *,
    user=None,
    request=None,
) -> tuple[Subscription, bool]:
    plan = get_default_plan()
    _, _, period_start, period_end = current_month_range()
    subscription, created = Subscription.objects.get_or_create(
        organization=organization,
        defaults={
            "plan": plan,
            "status": Subscription.Status.ACTIVE,
            "current_period_start": period_start,
            "current_period_end": period_end,
            "is_default": True,
            "created_by": user if getattr(user, "is_authenticated", False) else None,
        },
    )
    if created:
        record_audit_event(
            event_type=AuditEvent.EventType.BILLING_SUBSCRIPTION_CREATED,
            request=request,
            user=user,
            organization=organization,
            metadata={
                "subscription_id": subscription.id,
                "plan_code": plan.code,
                "default_subscription": True,
            },
        )
    return subscription, created


def get_monthly_usage_by_event(organization: Organization, *, month: date | None = None) -> dict[str, int]:
    starts_at, ends_at, _, _ = current_month_range(month)
    rows = (
        UsageEvent.objects.filter(
            organization=organization,
            created_at__gte=starts_at,
            created_at__lt=ends_at,
        )
        .values("event_type")
        .annotate(total=Sum("quantity"))
    )
    return {row["event_type"]: int(row["total"] or 0) for row in rows}


def get_usage_vs_limits(organization: Organization, *, month: date | None = None) -> dict[str, Any]:
    starts_at, ends_at, period_start, period_end = current_month_range(month)
    subscription = Subscription.objects.select_related("plan").filter(organization=organization).first()
    usage_by_event = get_monthly_usage_by_event(organization, month=month)
    quotas_by_event = {}
    if subscription is not None:
        quotas_by_event = {
            quota.usage_event_type: quota
            for quota in PlanQuota.objects.filter(plan=subscription.plan).order_by("usage_event_type")
        }

    event_types = sorted(set(usage_by_event) | set(quotas_by_event))
    rows = []
    for event_type in event_types:
        used = usage_by_event.get(event_type, 0)
        quota = quotas_by_event.get(event_type)
        is_unlimited = bool(quota and quota.is_unlimited)
        limit = None if is_unlimited or quota is None else quota.limit
        remaining = None if limit is None else max(limit - used, 0)
        exceeded = False if limit is None else used > limit
        if limit is None:
            percent_used = None
        elif limit == 0:
            percent_used = 100 if used else 0
        else:
            percent_used = round((used / limit) * 100, 2)
        rows.append(
            {
                "event_type": event_type,
                "used": used,
                "limit": limit,
                "remaining": remaining,
                "is_unlimited": is_unlimited,
                "exceeded": exceeded,
                "percent_used": percent_used,
            }
        )

    return {
        "organization": organization,
        "subscription": subscription,
        "plan": subscription.plan if subscription is not None else None,
        "period_start": period_start,
        "period_end": period_end,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "usage": rows,
        "hard_enforcement": False,
    }
