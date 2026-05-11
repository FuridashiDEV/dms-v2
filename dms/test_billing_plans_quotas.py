import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from dms.models import AuditEvent, Department, Document, Organization, Plan, PlanQuota, Subscription, UsageEvent, User
from dms.services.billing import (
    DEFAULT_PLAN_CODE,
    ensure_default_subscription,
    get_monthly_usage_by_event,
    get_usage_vs_limits,
)


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_billing_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class BillingPlansQuotasTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Billing Org",
            slug="billing-org",
        )
        self.department = Department.objects.create(
            name="Billing department",
            organization=self.organization,
        )
        self.user = User.objects.create_user(
            username="billing-user",
            password="password123",
            department=self.department,
        )

    def test_base_plans_and_quotas_are_seeded(self):
        plan_codes = set(Plan.objects.values_list("code", flat=True))

        self.assertTrue({"free", "team", "enterprise"}.issubset(plan_codes))
        self.assertTrue(
            PlanQuota.objects.filter(
                plan__code=DEFAULT_PLAN_CODE,
                usage_event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
                limit=100,
                is_unlimited=False,
            ).exists()
        )
        self.assertTrue(
            PlanQuota.objects.filter(
                plan__code="enterprise",
                usage_event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
                is_unlimited=True,
            ).exists()
        )

    def test_default_subscription_can_be_created_for_organization(self):
        subscription, created = ensure_default_subscription(self.organization, user=self.user)

        self.assertTrue(created)
        self.assertEqual(subscription.organization, self.organization)
        self.assertEqual(subscription.plan.code, DEFAULT_PLAN_CODE)
        self.assertEqual(subscription.status, Subscription.Status.ACTIVE)
        self.assertTrue(subscription.is_default)
        self.assertTrue(
            AuditEvent.objects.filter(
                organization=self.organization,
                event_type=AuditEvent.EventType.BILLING_SUBSCRIPTION_CREATED,
                metadata__subscription_id=subscription.id,
                metadata__plan_code=DEFAULT_PLAN_CODE,
            ).exists()
        )

    def test_existing_default_subscription_is_reused(self):
        first_subscription, first_created = ensure_default_subscription(self.organization, user=self.user)
        second_subscription, second_created = ensure_default_subscription(self.organization, user=self.user)

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first_subscription.id, second_subscription.id)
        self.assertEqual(Subscription.objects.filter(organization=self.organization).count(), 1)

    def test_monthly_usage_aggregation_uses_usage_events(self):
        ensure_default_subscription(self.organization, user=self.user)
        UsageEvent.objects.create(
            organization=self.organization,
            user=self.user,
            event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
            source="test",
            quantity=3,
        )
        UsageEvent.objects.create(
            organization=self.organization,
            user=self.user,
            event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
            source="test",
            quantity=2,
        )
        UsageEvent.objects.create(
            organization=self.organization,
            user=self.user,
            event_type=UsageEvent.EventType.AI_PROCESSING_STARTED,
            source="test",
            quantity=4,
        )

        usage = get_monthly_usage_by_event(self.organization)

        self.assertEqual(usage[UsageEvent.EventType.DOCUMENT_UPLOADED], 5)
        self.assertEqual(usage[UsageEvent.EventType.AI_PROCESSING_STARTED], 4)

    def test_usage_vs_limits_reports_exceeded_without_hard_enforcement(self):
        ensure_default_subscription(self.organization, user=self.user)
        UsageEvent.objects.create(
            organization=self.organization,
            user=self.user,
            event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
            source="test",
            quantity=101,
        )

        report = get_usage_vs_limits(self.organization)
        document_upload_row = next(
            row for row in report["usage"] if row["event_type"] == UsageEvent.EventType.DOCUMENT_UPLOADED
        )

        self.assertFalse(report["hard_enforcement"])
        self.assertEqual(document_upload_row["used"], 101)
        self.assertEqual(document_upload_row["limit"], 100)
        self.assertTrue(document_upload_row["exceeded"])

        document = Document.objects.create(
            department=self.department,
            title="Billing still allowed",
            file=SimpleUploadedFile("billing.txt", b"billing payload"),
            uploaded_by=self.user,
        )
        self.assertEqual(document.organization, self.organization)
