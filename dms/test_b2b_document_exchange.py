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


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_b2b_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class B2BDocumentExchangeTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="B2B department")
        self.other_department = Department.objects.create(name="B2B other")
        self.user = User.objects.create_user(
            username="b2b-user",
            password="password123",
            department=self.department,
        )
        self.outsider = User.objects.create_user(
            username="b2b-outsider",
            password="password123",
            department=self.other_department,
        )
        self.document = Document.objects.create(
            department=self.department,
            title="Outgoing B2B document",
            file=SimpleUploadedFile("outgoing.txt", b"outgoing payload"),
            uploaded_by=self.user,
        )
        self.document.create_version(uploaded_by=self.user)
        self.counterparty = Counterparty.objects.create(
            organization=self.department.organization,
            name="B2B LLP",
            email="b2b@example.com",
            created_by=self.user,
        )

    @patch("dms.services.counterparty.generate_exchange_token")
    def test_outgoing_flow_preserves_counterparty_portal_and_sets_b2b_fields(self, token_mock):
        token_mock.return_value = "stage10-outgoing-token"
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dms:document_exchange_send", args=[self.document.id]),
            {
                "counterparty": str(self.counterparty.id),
                "message": "Please review outgoing",
                "business_document_type": DocumentExchange.BusinessDocumentType.CONTRACT,
                "expires_days": "14",
            },
        )

        self.assertRedirects(response, reverse("dms:document_detail", args=[self.document.id]))
        exchange = DocumentExchange.objects.get(document=self.document)
        self.assertEqual(exchange.direction, DocumentExchange.Direction.OUTGOING)
        self.assertEqual(exchange.business_document_type, DocumentExchange.BusinessDocumentType.CONTRACT)
        self.assertEqual(exchange.status, DocumentExchange.Status.SENT)
        self.client.logout()
        portal_response = self.client.get(reverse("dms:counterparty_portal", args=["stage10-outgoing-token"]))
        self.assertEqual(portal_response.status_code, 200)

    def test_incoming_flow_creates_regular_document_version_exchange_and_audit(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dms:incoming_exchange_create"),
            {
                "counterparty": str(self.counterparty.id),
                "department": str(self.department.id),
                "title": "Incoming invoice",
                "description": "Received from B2B counterparty",
                "business_document_type": DocumentExchange.BusinessDocumentType.INVOICE,
                "message": "Incoming package",
                "file": SimpleUploadedFile("incoming.txt", b"incoming payload"),
            },
        )

        document = Document.objects.get(title="Incoming invoice")
        self.assertRedirects(response, reverse("dms:document_detail", args=[document.id]))
        self.assertEqual(document.source_system, "b2b_incoming_exchange")
        self.assertEqual(document.department, self.department)
        self.assertEqual(document.versions.count(), 1)

        exchange = DocumentExchange.objects.get(document=document)
        self.assertEqual(exchange.direction, DocumentExchange.Direction.INCOMING)
        self.assertEqual(exchange.status, DocumentExchange.Status.RECEIVED)
        self.assertEqual(exchange.business_document_type, DocumentExchange.BusinessDocumentType.INVOICE)
        self.assertEqual(exchange.received_by, self.user)
        self.assertTrue(
            ExchangeEvent.objects.filter(
                exchange=exchange,
                event_type=ExchangeEvent.EventType.RECEIVED,
                comment="Incoming package",
            ).exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                document=document,
                event_type=AuditEvent.EventType.EXCHANGE_RECEIVED,
                metadata__document_exchange_id=exchange.id,
            ).exists()
        )

    def test_exchange_list_filters_by_direction_status_and_counterparty(self):
        incoming_document = Document.objects.create(
            department=self.department,
            title="Incoming listed",
            file=SimpleUploadedFile("listed.txt", b"listed"),
            uploaded_by=self.user,
            source_system="b2b_incoming_exchange",
        )
        incoming_exchange = DocumentExchange.objects.create(
            organization=self.department.organization,
            document=incoming_document,
            counterparty=self.counterparty,
            direction=DocumentExchange.Direction.INCOMING,
            status=DocumentExchange.Status.RECEIVED,
            business_document_type=DocumentExchange.BusinessDocumentType.ACT,
            received_by=self.user,
            token_hash="incoming-list-token-hash",
        )
        other_counterparty = Counterparty.objects.create(
            organization=self.department.organization,
            name="Other B2B LLP",
        )
        DocumentExchange.objects.create(
            organization=self.department.organization,
            document=self.document,
            counterparty=other_counterparty,
            direction=DocumentExchange.Direction.OUTGOING,
            status=DocumentExchange.Status.SENT,
            sent_by=self.user,
            token_hash="outgoing-list-token-hash",
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dms:exchange_list"),
            {
                "direction": DocumentExchange.Direction.INCOMING,
                "status": DocumentExchange.Status.RECEIVED,
                "counterparty": str(self.counterparty.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        exchanges = list(response.context["exchanges"])
        self.assertEqual(exchanges, [incoming_exchange])
        self.assertContains(response, "Incoming listed")
        self.assertNotContains(response, "Outgoing B2B document")

    def test_employee_cannot_receive_incoming_for_unavailable_department(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dms:incoming_exchange_create"),
            {
                "new_counterparty_name": "Blocked incoming",
                "department": str(self.other_department.id),
                "title": "Blocked incoming doc",
                "file": SimpleUploadedFile("blocked.txt", b"blocked"),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.filter(title="Blocked incoming doc").exists())
        self.assertFalse(DocumentExchange.objects.filter(direction=DocumentExchange.Direction.INCOMING).exists())
