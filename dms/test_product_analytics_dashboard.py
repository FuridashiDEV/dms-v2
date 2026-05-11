import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dms.models import Department, Document, Organization, UsageEvent, User
from dms.services.analytics import build_organization_metrics, parse_date_range


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_analytics_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ProductAnalyticsDashboardTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Analytics Org",
            slug="analytics-org",
        )
        self.other_organization = Organization.objects.create(
            name="Hidden Analytics Org",
            slug="hidden-analytics-org",
        )
        self.department = Department.objects.create(
            name="Analytics department",
            organization=self.organization,
        )
        self.other_department = Department.objects.create(
            name="Hidden analytics department",
            organization=self.other_organization,
        )
        self.user = User.objects.create_user(
            username="analytics-user",
            password="password123",
            department=self.department,
        )
        self.other_user = User.objects.create_user(
            username="hidden-analytics-user",
            password="password123",
            department=self.other_department,
        )
        self.superuser = User.objects.create_superuser(
            username="analytics-superuser",
            password="password123",
        )

    def test_organization_metrics_use_usage_events_and_documents(self):
        Document.objects.create(
            department=self.department,
            title="Visible analytics document",
            file=SimpleUploadedFile("visible.txt", b"visible"),
            uploaded_by=self.user,
        )
        UsageEvent.objects.create(
            organization=self.organization,
            user=self.user,
            event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
            source="test",
            quantity=2,
        )

        metrics = build_organization_metrics(self.organization, parse_date_range({}))

        self.assertEqual(metrics["documents_uploaded"], 1)
        self.assertEqual(metrics["documents_total"], 1)
        self.assertEqual(metrics["usage_summary"][0]["event_type"], UsageEvent.EventType.DOCUMENT_UPLOADED)
        self.assertEqual(metrics["usage_summary"][0]["quantity"], 2)

    def test_dashboard_is_organization_scoped_for_regular_user(self):
        visible_document = Document.objects.create(
            department=self.department,
            title="Visible analytics document",
            file=SimpleUploadedFile("visible.txt", b"visible"),
            uploaded_by=self.user,
        )
        hidden_document = Document.objects.create(
            department=self.other_department,
            title="Hidden analytics document",
            file=SimpleUploadedFile("hidden.txt", b"hidden"),
            uploaded_by=self.other_user,
        )
        UsageEvent.objects.create(
            organization=self.organization,
            user=self.user,
            document=visible_document,
            event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
            source="test",
            quantity=1,
        )
        UsageEvent.objects.create(
            organization=self.other_organization,
            user=self.other_user,
            document=hidden_document,
            event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
            source="test",
            quantity=1,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dms:analytics_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Analytics Org")
        self.assertNotContains(response, "Hidden Analytics Org")
        self.assertNotContains(response, "Platform metrics")

    def test_regular_user_cannot_select_other_organization(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dms:analytics_dashboard"),
            {"organization": str(self.other_organization.id)},
        )

        self.assertEqual(response.status_code, 404)

    def test_superuser_can_view_platform_metrics(self):
        Document.objects.create(
            department=self.department,
            title="Visible analytics document",
            file=SimpleUploadedFile("visible.txt", b"visible"),
            uploaded_by=self.user,
        )
        Document.objects.create(
            department=self.other_department,
            title="Hidden analytics document",
            file=SimpleUploadedFile("hidden.txt", b"hidden"),
            uploaded_by=self.other_user,
        )
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("dms:analytics_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Platform metrics")
        self.assertContains(response, "Analytics Org")
        self.assertContains(response, "Hidden Analytics Org")

    def test_date_range_filters_usage_summary(self):
        current_event = UsageEvent.objects.create(
            organization=self.organization,
            user=self.user,
            event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
            source="test",
            quantity=3,
        )
        old_event = UsageEvent.objects.create(
            organization=self.organization,
            user=self.user,
            event_type=UsageEvent.EventType.AI_PROCESSING_STARTED,
            source="test",
            quantity=5,
        )
        old_date = timezone.now() - timedelta(days=90)
        UsageEvent.objects.filter(id=old_event.id).update(created_at=old_date)
        UsageEvent.objects.filter(id=current_event.id).update(created_at=timezone.now())

        metrics = build_organization_metrics(self.organization, parse_date_range({}))
        event_types = {row["event_type"] for row in metrics["usage_summary"]}

        self.assertIn(UsageEvent.EventType.DOCUMENT_UPLOADED, event_types)
        self.assertNotIn(UsageEvent.EventType.AI_PROCESSING_STARTED, event_types)
