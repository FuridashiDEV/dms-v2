import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import AuditEvent, DocumentActivity, UsageEvent
from dms.services.document_creation import create_document_from_uploaded_file
from dms.test_factories import make_document, make_org_context


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_qa_regression_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class QaCriticalRegressionTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.primary = make_org_context(
            slug="qa-primary",
            org_name="QA Primary Org",
            department_name="QA Primary Department",
            username="qa-primary-user",
        )
        self.other = make_org_context(
            slug="qa-other",
            org_name="QA Other Org",
            department_name="QA Other Department",
            username="qa-other-user",
        )
        self.document = make_document(
            context=self.primary,
            title="QA sensitive document",
            filename="qa-sensitive.txt",
        )
        self.other_document = make_document(
            context=self.other,
            title="QA hidden document",
            filename="qa-hidden.txt",
        )

    def test_document_creation_service_keeps_core_regression_chain(self):
        document, version = create_document_from_uploaded_file(
            uploaded_file=SimpleUploadedFile("qa-upload.txt", b"qa upload payload", content_type="text/plain"),
            department=self.primary.department,
            uploaded_by=self.primary.user,
            run_ai=False,
            indexer=lambda document: False,
        )

        self.assertEqual(document.organization, self.primary.organization)
        self.assertEqual(document.department, self.primary.department)
        self.assertEqual(version.document, document)
        self.assertEqual(version.number, 1)
        self.assertEqual(document.versions.count(), 1)
        self.assertTrue(document.checksum_sha256)
        self.assertTrue(
            DocumentActivity.objects.filter(
                document=document,
                user=self.primary.user,
                action=DocumentActivity.ACTION_UPLOADED,
            ).exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                document=document,
                event_type=AuditEvent.EventType.DOCUMENT_UPLOADED,
                metadata__document_version_id=version.id,
            ).exists()
        )
        self.assertTrue(
            UsageEvent.objects.filter(
                organization=self.primary.organization,
                document=document,
                event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
                metadata__document_version_id=version.id,
            ).exists()
        )

    def test_cross_organization_user_cannot_open_sensitive_document_routes(self):
        self.client.force_login(self.other.user)

        routes = [
            ("get", reverse("dms:document_detail", args=[self.document.id])),
            ("get", reverse("dms:document_view", args=[self.document.id])),
            ("get", reverse("dms:document_download", args=[self.document.id])),
            ("get", reverse("dms:document_evidence_export", args=[self.document.id])),
            ("get", reverse("dms:document_ai_review", args=[self.document.id])),
            ("post", reverse("dms:document_workflow_start", args=[self.document.id])),
            ("post", reverse("dms:document_exchange_send", args=[self.document.id])),
        ]

        for method, route in routes:
            with self.subTest(route=route):
                response = getattr(self.client, method)(route)
                self.assertIn(response.status_code, {403, 404})

    def test_regular_user_list_and_analytics_do_not_leak_other_organization(self):
        self.client.force_login(self.primary.user)

        list_response = self.client.get(reverse("dms:document_list"))
        analytics_response = self.client.get(reverse("dms:analytics_dashboard"))

        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "QA sensitive document")
        self.assertNotContains(list_response, "QA hidden document")
        self.assertEqual(analytics_response.status_code, 200)
        self.assertContains(analytics_response, "QA Primary Org")
        self.assertNotContains(analytics_response, "QA Other Org")

    def test_unauthenticated_product_routes_redirect_to_login(self):
        protected_routes = [
            reverse("dms:dashboard"),
            reverse("dms:document_list"),
            reverse("dms:analytics_dashboard"),
            reverse("dms:usage_dashboard"),
            reverse("dms:document_detail", args=[self.document.id]),
        ]

        for route in protected_routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login/", response["Location"])
