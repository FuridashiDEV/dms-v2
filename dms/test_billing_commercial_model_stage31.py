import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms import models
from dms.models import AuditEvent, Department, Document, Organization, Plan, PlanQuota, Subscription, UsageEvent, User
from dms.services.billing import BILLING_SUBSCRIPTION_CHANGED_EVENT, ensure_default_subscription, get_usage_vs_limits
from dms.services.document_creation import create_document_from_uploaded_file


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_billing_stage31_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class BillingCommercialModelStage31Tests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.organization = Organization.objects.create(name="Commercial Org", slug="commercial-org")
        self.other_organization = Organization.objects.create(name="Other Commercial Org", slug="other-commercial-org")
        self.department = Department.objects.create(name="Commercial department", organization=self.organization)
        self.other_department = Department.objects.create(name="Other commercial department", organization=self.other_organization)
        self.admin = User.objects.create_user(
            username="commercial-admin",
            password="password123",
            role=User.Role.ADMIN,
            department=self.department,
        )
        self.employee = User.objects.create_user(
            username="commercial-employee",
            password="password123",
            role=User.Role.EMPLOYEE,
            department=self.department,
        )
        self.other_admin = User.objects.create_user(
            username="commercial-other-admin",
            password="password123",
            role=User.Role.ADMIN,
            department=self.other_department,
        )
        self.superuser = User.objects.create_superuser(
            username="commercial-superuser",
            password="password123",
        )

    def test_organization_admin_sees_own_subscription(self):
        subscription, _ = ensure_default_subscription(self.organization, user=self.admin)
        self.client.force_login(self.admin)

        response = self.client.get(reverse("dms:billing_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["overview"]["subscription"], subscription)
        self.assertContains(response, "Commercial Org")
        self.assertContains(response, subscription.plan.name)

    def test_other_organization_cannot_see_subscription(self):
        ensure_default_subscription(self.other_organization, user=self.other_admin)
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("dms:billing_dashboard"),
            {"organization": str(self.other_organization.id)},
        )

        self.assertEqual(response.status_code, 404)

    def test_superuser_can_change_plan_manually(self):
        ensure_default_subscription(self.organization, user=self.admin)
        team_plan = Plan.objects.get(code="team")
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse("dms:billing_dashboard"),
            {
                "organization": str(self.organization.id),
                "plan_code": team_plan.code,
                "status": Subscription.Status.TRIALING,
                "reason": "Pilot commercial package",
            },
        )

        self.assertEqual(response.status_code, 302)
        subscription = Subscription.objects.get(organization=self.organization)
        self.assertEqual(subscription.plan, team_plan)
        self.assertEqual(subscription.status, Subscription.Status.TRIALING)
        self.assertFalse(subscription.is_default)
        self.assertTrue(
            AuditEvent.objects.filter(
                organization=self.organization,
                event_type=BILLING_SUBSCRIPTION_CHANGED_EVENT,
                metadata__old_plan_code="free",
                metadata__new_plan_code="team",
                metadata__payment_gateway_enabled=False,
                metadata__invoice_created=False,
            ).exists()
        )

    def test_usage_report_shows_exceeded_limits(self):
        ensure_default_subscription(self.organization, user=self.admin)
        UsageEvent.objects.create(
            organization=self.organization,
            user=self.admin,
            event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
            source="test",
            quantity=101,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("dms:billing_usage_limits"))

        self.assertEqual(response.status_code, 200)
        row = next(row for row in response.context["report"]["usage"] if row["event_type"] == UsageEvent.EventType.DOCUMENT_UPLOADED)
        self.assertTrue(row["exceeded"])
        self.assertEqual(row["warning_level"], "exceeded")
        self.assertContains(response, "Soft limit exceeded")

    def test_soft_warning_does_not_block_product_flow(self):
        plan = Plan.objects.get(code="free")
        PlanQuota.objects.filter(
            plan=plan,
            usage_event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
        ).update(limit=1, is_unlimited=False)
        ensure_default_subscription(self.organization, user=self.admin)
        UsageEvent.objects.create(
            organization=self.organization,
            user=self.admin,
            event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
            source="test",
            quantity=2,
        )

        report = get_usage_vs_limits(self.organization)
        row = next(row for row in report["usage"] if row["event_type"] == UsageEvent.EventType.DOCUMENT_UPLOADED)
        self.assertTrue(row["exceeded"])
        self.assertFalse(report["hard_enforcement"])

        document, version = create_document_from_uploaded_file(
            uploaded_file=SimpleUploadedFile("still-allowed.txt", b"allowed"),
            department=self.department,
            uploaded_by=self.admin,
            run_ai=False,
            indexer=lambda document: False,
        )
        self.assertEqual(document.organization, self.organization)
        self.assertEqual(version.number, 1)

    def test_no_payment_logic_exists(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dms:billing_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["overview"]["payment_gateway_enabled"])
        self.assertFalse(response.context["overview"]["invoices_enabled"])
        self.assertFalse(hasattr(models, "Invoice"))
        self.assertContains(response, "no payments, invoices, or hard blocking")

    def test_employee_cannot_access_billing_screens(self):
        self.client.force_login(self.employee)

        self.assertEqual(self.client.get(reverse("dms:billing_dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("dms:billing_usage_limits")).status_code, 403)
