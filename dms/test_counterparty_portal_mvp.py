import hashlib
import shutil
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import (
    AuditEvent,
    Counterparty,
    Department,
    Document,
    DocumentExchange,
    ExchangeEvent,
    User,
)


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_counterparty_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class CounterpartyPortalMvpTests(TestCase):
    token = "stage09-secure-token"

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="Counterparty department")
        self.other_department = Department.objects.create(name="Counterparty other")
        self.user = User.objects.create_user(
            username="counterparty-user",
            password="password123",
            department=self.department,
        )
        self.outsider = User.objects.create_user(
            username="counterparty-outsider",
            password="password123",
            department=self.other_department,
        )
        self.document = Document.objects.create(
            department=self.department,
            title="Counterparty contract",
            file=SimpleUploadedFile("contract.txt", b"counterparty payload"),
            uploaded_by=self.user,
        )
        self.document.create_version(uploaded_by=self.user)

    @patch("dms.services.counterparty.generate_exchange_token")
    def test_internal_send_creates_counterparty_exchange_events_and_audit(self, token_mock):
        token_mock.return_value = self.token
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dms:document_exchange_send", args=[self.document.id]),
            {
                "new_counterparty_name": "Acme LLP",
                "new_counterparty_email": "legal@example.com",
                "new_contact_name": "Legal Contact",
                "message": "Please review",
                "expires_days": "7",
            },
        )

        self.assertRedirects(response, reverse("dms:document_detail", args=[self.document.id]))
        counterparty = Counterparty.objects.get(name="Acme LLP")
        exchange = DocumentExchange.objects.get(document=self.document, counterparty=counterparty)
        self.assertEqual(exchange.status, DocumentExchange.Status.SENT)
        self.assertEqual(
            exchange.token_hash,
            hashlib.sha256(self.token.encode("utf-8")).hexdigest(),
        )
        self.assertNotEqual(exchange.token_hash, self.token)
        self.assertEqual(exchange.token_hint, self.token[-8:])
        self.assertTrue(
            ExchangeEvent.objects.filter(
                exchange=exchange,
                event_type=ExchangeEvent.EventType.SENT,
                comment="Please review",
            ).exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                document=self.document,
                event_type=AuditEvent.EventType.EXCHANGE_SENT,
                metadata__document_exchange_id=exchange.id,
            ).exists()
        )

    @patch("dms.services.counterparty.generate_exchange_token")
    def test_external_portal_open_download_accept_and_comment(self, token_mock):
        token_mock.return_value = self.token
        self.client.force_login(self.user)
        self.client.post(
            reverse("dms:document_exchange_send", args=[self.document.id]),
            {
                "new_counterparty_name": "Portal LLP",
                "message": "External review",
                "expires_days": "7",
            },
        )
        self.client.logout()
        exchange = DocumentExchange.objects.get(document=self.document)

        portal_response = self.client.get(reverse("dms:counterparty_portal", args=[self.token]))
        self.assertEqual(portal_response.status_code, 200)
        exchange.refresh_from_db()
        self.assertEqual(exchange.status, DocumentExchange.Status.OPENED)
        self.assertTrue(
            ExchangeEvent.objects.filter(
                exchange=exchange,
                event_type=ExchangeEvent.EventType.OPENED,
            ).exists()
        )

        download_response = self.client.get(reverse("dms:counterparty_portal_download", args=[self.token]))
        self.assertEqual(download_response.status_code, 200)
        self.assertTrue(
            ExchangeEvent.objects.filter(
                exchange=exchange,
                event_type=ExchangeEvent.EventType.DOWNLOADED,
            ).exists()
        )

        comment_response = self.client.post(
            reverse("dms:counterparty_portal_action", args=[self.token, "comment"]),
            {"comment": "Question from counterparty"},
        )
        self.assertRedirects(comment_response, reverse("dms:counterparty_portal", args=[self.token]))
        self.assertTrue(
            ExchangeEvent.objects.filter(
                exchange=exchange,
                event_type=ExchangeEvent.EventType.COMMENTED,
                comment="Question from counterparty",
            ).exists()
        )

        accept_response = self.client.post(
            reverse("dms:counterparty_portal_action", args=[self.token, "accept"]),
            {"comment": "Accepted"},
        )
        self.assertRedirects(accept_response, reverse("dms:counterparty_portal", args=[self.token]))
        exchange.refresh_from_db()
        self.assertEqual(exchange.status, DocumentExchange.Status.ACCEPTED)
        self.assertTrue(
            AuditEvent.objects.filter(
                document=self.document,
                event_type=AuditEvent.EventType.EXCHANGE_ACCEPTED,
                metadata__document_exchange_id=exchange.id,
            ).exists()
        )

    @patch("dms.services.counterparty.generate_exchange_token")
    def test_external_portal_rejects_exchange(self, token_mock):
        token_mock.return_value = self.token
        self.client.force_login(self.user)
        self.client.post(
            reverse("dms:document_exchange_send", args=[self.document.id]),
            {
                "new_counterparty_name": "Reject LLP",
                "expires_days": "7",
            },
        )
        self.client.logout()
        exchange = DocumentExchange.objects.get(document=self.document)

        response = self.client.post(
            reverse("dms:counterparty_portal_action", args=[self.token, "reject"]),
            {"comment": "Rejected"},
        )

        self.assertRedirects(response, reverse("dms:counterparty_portal", args=[self.token]))
        exchange.refresh_from_db()
        self.assertEqual(exchange.status, DocumentExchange.Status.REJECTED)
        self.assertTrue(
            ExchangeEvent.objects.filter(
                exchange=exchange,
                event_type=ExchangeEvent.EventType.REJECTED,
                comment="Rejected",
            ).exists()
        )

    def test_outsider_cannot_send_document_exchange(self):
        self.client.force_login(self.outsider)

        response = self.client.post(
            reverse("dms:document_exchange_send", args=[self.document.id]),
            {
                "new_counterparty_name": "Blocked LLP",
                "expires_days": "7",
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(DocumentExchange.objects.exists())
        self.assertFalse(Counterparty.objects.exists())
