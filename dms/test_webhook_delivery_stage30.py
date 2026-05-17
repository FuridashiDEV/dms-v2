import json
import shutil
import tempfile

from django.test import TestCase, override_settings
from django.utils import timezone

from dms.models import Department, UsageEvent, User, WebhookDelivery, WebhookEndpoint
from dms.services.usage import hash_webhook_secret, record_usage_event
from dms.services.webhooks import WebhookHttpResponse, retry_webhook_delivery, send_due_webhook_deliveries, send_webhook_delivery


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_webhook_delivery_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, DMS_WEBHOOK_RETRY_BASE_SECONDS=1)
class WebhookDeliveryStage30Tests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="Webhook delivery")
        self.user = User.objects.create_user(
            username="webhook-delivery-user",
            password="password123",
            department=self.department,
        )
        self.secret = "super-secret-webhook"
        self.endpoint = WebhookEndpoint.objects.create(
            organization=self.department.organization,
            name="Delivery endpoint",
            url="https://example.test/webhooks/dms",
            event_types=[UsageEvent.EventType.DOCUMENT_UPLOADED],
            secret_hash=hash_webhook_secret(self.secret),
            created_by=self.user,
        )

    def queue_delivery(self, metadata=None):
        usage_event = record_usage_event(
            event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
            organization=self.department.organization,
            user=self.user,
            source="test",
            metadata=metadata or {"visible": "kept"},
        )
        return WebhookDelivery.objects.get(usage_event=usage_event)

    def secret_resolver(self, endpoint):
        return self.secret

    def test_delivery_posts_to_endpoint_and_marks_sent(self):
        delivery = self.queue_delivery()
        calls = []

        def transport(url, body, headers, timeout):
            calls.append((url, body, headers, timeout))
            return WebhookHttpResponse(status_code=204, body="")

        result = send_webhook_delivery(delivery, transport=transport, secret_resolver=self.secret_resolver)

        self.assertEqual(result.status, WebhookDelivery.Status.SENT)
        self.assertEqual(result.response_status, 204)
        self.assertEqual(result.attempt_count, 1)
        self.assertEqual(calls[0][0], self.endpoint.url)
        self.assertEqual(calls[0][3], 5)
        self.assertEqual(calls[0][2]["X-DMS-Event"], UsageEvent.EventType.DOCUMENT_UPLOADED)
        self.assertEqual(calls[0][2]["X-DMS-Delivery-ID"], str(delivery.id))
        self.assertTrue(calls[0][2]["X-DMS-Signature"].startswith("sha256="))
        self.assertIn('"visible":"kept"', calls[0][1].decode("utf-8"))
        self.assertNotIn(self.secret, calls[0][1].decode("utf-8"))

    def test_failed_response_increments_attempt_and_schedules_retry(self):
        delivery = self.queue_delivery()

        result = send_webhook_delivery(
            delivery,
            transport=lambda url, body, headers, timeout: WebhookHttpResponse(status_code=500, body="server error"),
            secret_resolver=self.secret_resolver,
            max_attempts=3,
        )

        self.assertEqual(result.status, WebhookDelivery.Status.PENDING)
        self.assertEqual(result.response_status, 500)
        self.assertEqual(result.attempt_count, 1)
        self.assertEqual(result.last_error, "HTTP 500")
        self.assertIsNotNone(result.next_attempt_at)
        self.assertGreater(result.next_attempt_at, timezone.now())

    def test_max_attempts_marks_delivery_failed(self):
        delivery = self.queue_delivery()

        result = send_webhook_delivery(
            delivery,
            transport=lambda url, body, headers, timeout: WebhookHttpResponse(status_code=503, body="unavailable"),
            secret_resolver=self.secret_resolver,
            max_attempts=1,
        )

        self.assertEqual(result.status, WebhookDelivery.Status.FAILED)
        self.assertEqual(result.attempt_count, 1)
        self.assertEqual(result.response_status, 503)
        self.assertIsNone(result.next_attempt_at)

    def test_payload_is_sanitized_before_delivery(self):
        delivery = self.queue_delivery(
            metadata={
                "visible": "kept",
                "secure_token": "do-not-send",
                "nested": {"api_key": "do-not-send-either", "ok": True},
            }
        )
        delivery.payload["webhook_secret"] = "do-not-send"
        delivery.payload["portal_url"] = "https://example.test/portal/token-value"
        delivery.save(update_fields=["payload"])
        bodies = []

        def transport(url, body, headers, timeout):
            bodies.append(body.decode("utf-8"))
            return WebhookHttpResponse(status_code=200)

        result = send_webhook_delivery(delivery, transport=transport, secret_resolver=self.secret_resolver)

        self.assertEqual(result.status, WebhookDelivery.Status.SENT)
        body = bodies[0]
        self.assertIn("visible", body)
        self.assertIn("portal_url", body)
        self.assertNotIn("secure_token", body)
        self.assertNotIn("api_key", body)
        self.assertNotIn("webhook_secret", body)
        self.assertNotIn("do-not-send", body)
        result.refresh_from_db()
        stored_payload = json.dumps(result.payload)
        self.assertNotIn("secure_token", stored_payload)
        self.assertNotIn("webhook_secret", stored_payload)

    def test_secret_is_redacted_from_transport_error(self):
        delivery = self.queue_delivery()

        def transport(url, body, headers, timeout):
            raise RuntimeError(f"authorization={self.secret}")

        result = send_webhook_delivery(
            delivery,
            transport=transport,
            secret_resolver=self.secret_resolver,
            max_attempts=1,
        )

        self.assertEqual(result.status, WebhookDelivery.Status.FAILED)
        self.assertNotIn(self.secret, result.last_error)
        self.assertIn("[redacted]", result.last_error)

    def test_due_deliveries_and_manual_retry_use_service(self):
        delivery = self.queue_delivery()
        delivery.next_attempt_at = timezone.now()
        delivery.save(update_fields=["next_attempt_at"])

        sent = send_due_webhook_deliveries(
            transport=lambda url, body, headers, timeout: WebhookHttpResponse(status_code=500),
            secret_resolver=self.secret_resolver,
            max_attempts=1,
        )
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].status, WebhookDelivery.Status.FAILED)

        retried = retry_webhook_delivery(
            sent[0],
            transport=lambda url, body, headers, timeout: WebhookHttpResponse(status_code=200),
            secret_resolver=self.secret_resolver,
        )
        self.assertEqual(retried.status, WebhookDelivery.Status.SENT)
        self.assertEqual(retried.attempt_count, 2)
