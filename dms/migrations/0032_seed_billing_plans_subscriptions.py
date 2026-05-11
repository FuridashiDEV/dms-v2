from datetime import date
from decimal import Decimal

from django.db import migrations
from django.utils import timezone


PLAN_DEFINITIONS = [
    {
        "code": "free",
        "name": "Free",
        "description": "Default internal foundation plan. Report-only quotas, no billing enforcement.",
        "billing_interval": "manual",
        "price_amount": Decimal("0.00"),
        "currency": "KZT",
        "quotas": {
            "document.uploaded": 100,
            "import.file_imported": 100,
            "ai.processing_started": 50,
            "workflow.action": 100,
            "exchange.event": 50,
            "evidence.exported": 20,
            "integration.external_reference_linked": 100,
        },
    },
    {
        "code": "team",
        "name": "Team",
        "description": "Internal growth plan placeholder. Report-only quotas, no billing enforcement.",
        "billing_interval": "manual",
        "price_amount": Decimal("0.00"),
        "currency": "KZT",
        "quotas": {
            "document.uploaded": 5000,
            "import.file_imported": 5000,
            "ai.processing_started": 2000,
            "workflow.action": 3000,
            "exchange.event": 1000,
            "evidence.exported": 500,
            "integration.external_reference_linked": 5000,
        },
    },
    {
        "code": "enterprise",
        "name": "Enterprise",
        "description": "Internal enterprise placeholder. Unlimited report-only quotas, no billing enforcement.",
        "billing_interval": "manual",
        "price_amount": Decimal("0.00"),
        "currency": "KZT",
        "quotas": {
            "document.uploaded": None,
            "import.file_imported": None,
            "ai.processing_started": None,
            "workflow.action": None,
            "exchange.event": None,
            "evidence.exported": None,
            "integration.external_reference_linked": None,
        },
    },
]


def first_day_of_next_month(value):
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def seed_billing_plans_and_subscriptions(apps, schema_editor):
    Plan = apps.get_model("dms", "Plan")
    PlanQuota = apps.get_model("dms", "PlanQuota")
    Subscription = apps.get_model("dms", "Subscription")
    Organization = apps.get_model("dms", "Organization")

    plans = {}
    for plan_data in PLAN_DEFINITIONS:
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
        plans[plan_data["code"]] = plan
        for usage_event_type, limit in quotas.items():
            PlanQuota.objects.update_or_create(
                plan=plan,
                usage_event_type=usage_event_type,
                defaults={
                    "limit": 0 if limit is None else int(limit),
                    "is_unlimited": limit is None,
                },
            )

    free_plan = plans["free"]
    period_start = timezone.localdate().replace(day=1)
    period_end = first_day_of_next_month(period_start)
    for organization in Organization.objects.all():
        Subscription.objects.get_or_create(
            organization=organization,
            defaults={
                "plan": free_plan,
                "status": "ACTIVE",
                "current_period_start": period_start,
                "current_period_end": period_end,
                "is_default": True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("dms", "0031_plan_alter_auditevent_event_type_planquota_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_billing_plans_and_subscriptions, migrations.RunPython.noop),
    ]
