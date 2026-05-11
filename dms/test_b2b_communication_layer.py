import shutil
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import (
    AuditEvent,
    Counterparty,
    CounterpartyContact,
    Department,
    Document,
    DocumentExchange,
    ExchangeEvent,
    ExchangeMessage,
    User,
)


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_b2b_comm_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class B2BCommunicationLayerTests(TestCase):
    token = "stage10-1-token"

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="B2B comm department")
        self.other_department = Department.objects.create(name="B2B comm other")
        self.user = User.objects.create_user(
            username="b2b-comm-user",
            password="password123",
            department=self.department,
        )
        self.outsider = User.objects.create_user(
            username="b2b-comm-outsider",
            password="password123",
            department=self.other_department,
        )
        self.document = Document.objects.create(
            department=self.department,
            title="B2B comm document",
            file=SimpleUploadedFile("comm.txt", b"communication payload"),
            uploaded_by=self.user,
        )
        self.document.create_version(uploaded_by=self.user)
        self.counterparty = Counterparty.objects.create(
            organization=self.department.organization,
            name="Communication LLP",
            email="company@example.com",
            created_by=self.user,
        )

    @patch("dms.services.counterparty.generate_exchange_token")
    def test_outgoing_exchange_creates_contact_and_initial_internal_message(self, token_mock):
        token_mock.return_value = self.token
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dms:document_exchange_send", args=[self.document.id]),
            {
                "counterparty": str(self.counterparty.id),
                "new_contact_name": "Legal Contact",
                "new_contact_email": "legal@example.com",
                "message": "Initial internal note",
                "expires_days": "14",
            },
        )

        self.assertRedirects(response, reverse("dms:document_detail", args=[self.document.id]))
        contact = CounterpartyContact.objects.get(counterparty=self.counterparty)
        self.assertEqual(contact.name, "Legal Contact")
        self.assertEqual(contact.email, "legal@example.com")
        exchange = DocumentExchange.objects.get(document=self.document)
        self.assertEqual(exchange.counterparty_contact, contact)
        self.assertTrue(
            ExchangeMessage.objects.filter(
                exchange=exchange,
                author_type=ExchangeMessage.AuthorType.INTERNAL,
                user=self.user,
                body="Initial internal note",
                source_event_type=ExchangeEvent.EventType.SENT,
            ).exists()
        )

    def test_internal_message_flow_records_message_event_and_audit(self):
        exchange = DocumentExchange.objects.create(
            organization=self.department.organization,
            document=self.document,
            counterparty=self.counterparty,
            direction=DocumentExchange.Direction.OUTGOING,
            status=DocumentExchange.Status.SENT,
            sent_by=self.user,
            token_hash="stage10-1-internal-message-hash",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dms:exchange_message_create", args=[exchange.id]),
            {"body": "Internal follow-up"},
        )

        self.assertRedirects(response, reverse("dms:document_detail", args=[self.document.id]))
        message = ExchangeMessage.objects.get(exchange=exchange)
        self.assertEqual(message.author_type, ExchangeMessage.AuthorType.INTERNAL)
        self.assertEqual(message.user, self.user)
        self.assertEqual(message.body, "Internal follow-up")
        self.assertTrue(
            ExchangeEvent.objects.filter(
                exchange=exchange,
                event_type=ExchangeEvent.EventType.COMMENTED,
                comment="Internal follow-up",
            ).exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                document=self.document,
                event_type=AuditEvent.EventType.EXCHANGE_COMMENTED,
                metadata__exchange_message_id=message.id,
            ).exists()
        )

    @patch("dms.services.counterparty.generate_exchange_token")
    def test_external_portal_comment_and_accept_comments_become_exchange_messages(self, token_mock):
        token_mock.return_value = self.token
        self.client.force_login(self.user)
        self.client.post(
            reverse("dms:document_exchange_send", args=[self.document.id]),
            {
                "counterparty": str(self.counterparty.id),
                "new_contact_name": "Portal Contact",
                "new_contact_email": "portal@example.com",
                "expires_days": "7",
            },
        )
        self.client.logout()
        exchange = DocumentExchange.objects.get(document=self.document)

        comment_response = self.client.post(
            reverse("dms:counterparty_portal_action", args=[self.token, "comment"]),
            {"comment": "External question"},
        )
        self.assertRedirects(comment_response, reverse("dms:counterparty_portal", args=[self.token]))
        self.assertTrue(
            ExchangeMessage.objects.filter(
                exchange=exchange,
                author_type=ExchangeMessage.AuthorType.EXTERNAL,
                body="External question",
                source_event_type=ExchangeEvent.EventType.COMMENTED,
            ).exists()
        )
        self.assertTrue(
            ExchangeEvent.objects.filter(
                exchange=exchange,
                event_type=ExchangeEvent.EventType.COMMENTED,
                comment="External question",
            ).exists()
        )

        accept_response = self.client.post(
            reverse("dms:counterparty_portal_action", args=[self.token, "accept"]),
            {"comment": "Accepted with note"},
        )
        self.assertRedirects(accept_response, reverse("dms:counterparty_portal", args=[self.token]))
        exchange.refresh_from_db()
        self.assertEqual(exchange.status, DocumentExchange.Status.ACCEPTED)
        self.assertTrue(
            ExchangeMessage.objects.filter(
                exchange=exchange,
                author_type=ExchangeMessage.AuthorType.EXTERNAL,
                body="Accepted with note",
                source_event_type=ExchangeEvent.EventType.ACCEPTED,
            ).exists()
        )

    def test_outsider_cannot_create_internal_exchange_message(self):
        exchange = DocumentExchange.objects.create(
            organization=self.department.organization,
            document=self.document,
            counterparty=self.counterparty,
            direction=DocumentExchange.Direction.OUTGOING,
            status=DocumentExchange.Status.SENT,
            sent_by=self.user,
            token_hash="stage10-1-outsider-message-hash",
        )
        self.client.force_login(self.outsider)

        response = self.client.post(
            reverse("dms:exchange_message_create", args=[exchange.id]),
            {"body": "Unauthorized"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(ExchangeMessage.objects.filter(exchange=exchange).exists())
