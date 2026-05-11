import json
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import (
    Department,
    Document,
    Organization,
    UsageEvent,
    User,
    WebhookDelivery,
    WebhookEndpoint,
)
from dms.services.document_creation import create_document_from_uploaded_file
from dms.services.usage import hash_webhook_secret, record_usage_event


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_usage_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ApiWebhooksUsageTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="Usage department")
        self.user = User.objects.create_user(
            username="usage-user",
            password="password123",
            department=self.department,
        )
        self.other_organization = Organization.objects.create(
            name="Other Usage Org",
            slug="other-usage-org",
        )
        self.other_department = Department.objects.create(
            name="Usage other",
            organization=self.other_organization,
        )
        self.other_user = User.objects.create_user(
            username="usage-other",
            password="password123",
            department=self.other_department,
        )

    def test_document_upload_records_usage_and_queues_webhook_delivery(self):
        endpoint = WebhookEndpoint.objects.create(
            organization=self.department.organization,
            name="Usage endpoint",
            url="https://example.test/webhooks/usage",
            event_types=[UsageEvent.EventType.DOCUMENT_UPLOADED],
            secret_hash=hash_webhook_secret("super-secret-webhook"),
            created_by=self.user,
        )

        document, version = create_document_from_uploaded_file(
            uploaded_file=SimpleUploadedFile("usage.txt", b"usage payload"),
            department=self.department,
            uploaded_by=self.user,
            run_ai=False,
            indexer=lambda document: False,
        )

        usage_event = UsageEvent.objects.get(
            organization=self.department.organization,
            document=document,
            event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
        )
        self.assertEqual(usage_event.user, self.user)
        self.assertEqual(usage_event.metadata["document_version_id"], version.id)

        delivery = WebhookDelivery.objects.get(endpoint=endpoint, usage_event=usage_event)
        self.assertEqual(delivery.status, WebhookDelivery.Status.PENDING)
        self.assertEqual(delivery.payload["type"], UsageEvent.EventType.DOCUMENT_UPLOADED)
        raw_payload = json.dumps(delivery.payload)
        self.assertNotIn("super-secret-webhook", raw_payload)
        self.assertNotIn("secret_hash", raw_payload)

    def test_usage_service_sanitizes_sensitive_metadata_and_filters_webhooks(self):
        matching_endpoint = WebhookEndpoint.objects.create(
            organization=self.department.organization,
            name="Matching endpoint",
            url="https://example.test/webhooks/matching",
            event_types=[UsageEvent.EventType.EVIDENCE_EXPORTED],
        )
        WebhookEndpoint.objects.create(
            organization=self.department.organization,
            name="Non matching endpoint",
            url="https://example.test/webhooks/non-matching",
            event_types=[UsageEvent.EventType.DOCUMENT_UPLOADED],
        )

        usage_event = record_usage_event(
            event_type=UsageEvent.EventType.EVIDENCE_EXPORTED,
            organization=self.department.organization,
            user=self.user,
            source="test",
            metadata={
                "visible": "kept",
                "secure_token": "do-not-store",
                "nested": {"api_key": "do-not-store-either"},
            },
        )

        self.assertIsNotNone(usage_event)
        usage_event.refresh_from_db()
        self.assertEqual(usage_event.metadata["visible"], "kept")
        self.assertNotIn("secure_token", usage_event.metadata)
        self.assertEqual(usage_event.metadata["nested"], {})
        self.assertEqual(WebhookDelivery.objects.count(), 1)
        self.assertEqual(WebhookDelivery.objects.get().endpoint, matching_endpoint)

    def test_usage_dashboard_is_organization_scoped(self):
        visible_document = Document.objects.create(
            department=self.department,
            title="Visible usage doc",
            file=SimpleUploadedFile("visible.txt", b"visible"),
            uploaded_by=self.user,
        )
        hidden_document = Document.objects.create(
            department=self.other_department,
            title="Hidden usage doc",
            file=SimpleUploadedFile("hidden.txt", b"hidden"),
            uploaded_by=self.other_user,
        )
        record_usage_event(
            event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
            user=self.user,
            document=visible_document,
        )
        record_usage_event(
            event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
            user=self.other_user,
            document=hidden_document,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dms:usage_dashboard"))

        self.assertEqual(response.status_code, 200)
        events = list(response.context["usage_events"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].document, visible_document)
        self.assertContains(response, "Visible usage doc")
        self.assertNotContains(response, "Hidden usage doc")

    def test_evidence_export_records_usage_event(self):
        document = Document.objects.create(
            department=self.department,
            title="Evidence usage doc",
            file=SimpleUploadedFile("evidence.txt", b"evidence"),
            uploaded_by=self.user,
        )
        document.create_version(uploaded_by=self.user)
        self.client.force_login(self.user)

        response = self.client.get(reverse("dms:document_evidence_export", args=[document.id]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            UsageEvent.objects.filter(
                organization=self.department.organization,
                document=document,
                user=self.user,
                event_type=UsageEvent.EventType.EVIDENCE_EXPORTED,
                metadata__evidence_format="json",
            ).exists()
        )
