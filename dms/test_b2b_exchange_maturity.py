import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dms.models import (
    AuditEvent,
    CounterpartyContact,
    DocumentExchange,
    ExchangeEvent,
)
from dms.services.counterparty import create_document_exchange, hash_exchange_token
from dms.test_factories import make_counterparty, make_document, make_org_context


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_b2b_maturity_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class B2BExchangeMaturityTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.context = make_org_context(slug="b2b-maturity", username="b2b-maturity-user")
        self.other_context = make_org_context(slug="b2b-maturity-other", username="b2b-maturity-outsider")
        self.document = make_document(context=self.context, title="Maturity exchange document")
        self.counterparty = make_counterparty(context=self.context, name="Maturity LLP", email="maturity@example.test")
        self.contact = CounterpartyContact.objects.create(
            counterparty=self.counterparty,
            name="Maturity Contact",
            email="contact@example.test",
            created_by=self.context.user,
        )

    @patch("dms.services.counterparty.generate_exchange_token", return_value="maturity-detail-token")
    def test_exchange_card_is_visible_to_allowed_user_only(self, _token_mock):
        created = create_document_exchange(
            document=self.document,
            counterparty=self.counterparty,
            counterparty_contact=self.contact,
            user=self.context.user,
            message="Review the maturity exchange",
            expires_at=timezone.now() + timedelta(days=7),
        )

        self.client.force_login(self.context.user)
        response = self.client.get(reverse("dms:exchange_detail", args=[created.exchange.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Exchange card")
        self.assertContains(response, "Maturity exchange document")
        self.assertContains(response, "Maturity LLP")
        self.assertContains(response, "Maturity Contact")

        self.client.force_login(self.other_context.user)
        response = self.client.get(reverse("dms:exchange_detail", args=[created.exchange.id]))
        self.assertEqual(response.status_code, 404)

    @patch("dms.services.counterparty.generate_exchange_token", return_value="maturity-revoke-token")
    def test_revoke_link_blocks_portal_and_records_events(self, _token_mock):
        created = create_document_exchange(
            document=self.document,
            counterparty=self.counterparty,
            user=self.context.user,
            expires_at=timezone.now() + timedelta(days=7),
        )
        self.client.force_login(self.context.user)

        response = self.client.post(reverse("dms:exchange_revoke", args=[created.exchange.id]))

        self.assertRedirects(response, reverse("dms:exchange_detail", args=[created.exchange.id]))
        created.exchange.refresh_from_db()
        self.assertEqual(created.exchange.status, DocumentExchange.Status.REVOKED)
        self.assertTrue(
            ExchangeEvent.objects.filter(
                exchange=created.exchange,
                event_type=ExchangeEvent.EventType.REVOKED,
            ).exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                document=self.document,
                event_type=AuditEvent.EventType.EXCHANGE_REVOKED,
                metadata__document_exchange_id=created.exchange.id,
            ).exists()
        )

        self.client.logout()
        portal_response = self.client.get(reverse("dms:counterparty_portal", args=[created.token]))
        self.assertEqual(portal_response.status_code, 200)
        self.assertContains(portal_response, "Exchange link unavailable")
        self.assertNotContains(portal_response, "Maturity exchange document")
        download_response = self.client.get(reverse("dms:counterparty_portal_download", args=[created.token]))
        self.assertEqual(download_response.status_code, 404)

    @patch("dms.services.counterparty.generate_exchange_token", return_value="maturity-expired-token")
    def test_expired_link_cannot_download_and_records_audit(self, _token_mock):
        created = create_document_exchange(
            document=self.document,
            counterparty=self.counterparty,
            user=self.context.user,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        response = self.client.get(reverse("dms:counterparty_portal_download", args=[created.token]))

        self.assertEqual(response.status_code, 404)
        created.exchange.refresh_from_db()
        self.assertEqual(created.exchange.status, DocumentExchange.Status.EXPIRED)
        self.assertTrue(
            ExchangeEvent.objects.filter(
                exchange=created.exchange,
                event_type=ExchangeEvent.EventType.EXPIRED,
            ).exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                document=self.document,
                event_type=AuditEvent.EventType.EXCHANGE_EXPIRED,
                metadata__document_exchange_id=created.exchange.id,
            ).exists()
        )

    @patch("dms.services.counterparty.generate_exchange_token")
    def test_resend_reissues_secure_token_and_keeps_same_exchange(self, token_mock):
        token_mock.return_value = "maturity-old-token"
        created = create_document_exchange(
            document=self.document,
            counterparty=self.counterparty,
            user=self.context.user,
            expires_at=timezone.now() + timedelta(days=7),
        )
        original_exchange_id = created.exchange.id
        self.client.force_login(self.context.user)

        token_mock.return_value = "maturity-new-token"
        response = self.client.post(
            reverse("dms:exchange_resend", args=[original_exchange_id]),
            {"expires_days": "10", "message": "Resent for review"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "maturity-new-token")
        exchange = DocumentExchange.objects.get(pk=original_exchange_id)
        self.assertEqual(exchange.status, DocumentExchange.Status.SENT)
        self.assertEqual(exchange.token_hash, hash_exchange_token("maturity-new-token"))
        self.assertEqual(exchange.token_hint, "maturity-new-token"[-8:])
        self.assertTrue(exchange.is_link_active)
        self.assertEqual(
            ExchangeEvent.objects.filter(
                exchange=exchange,
                event_type=ExchangeEvent.EventType.SENT,
            ).count(),
            2,
        )

        self.client.logout()
        old_response = self.client.get(reverse("dms:counterparty_portal", args=["maturity-old-token"]))
        self.assertEqual(old_response.status_code, 404)
        new_response = self.client.get(reverse("dms:counterparty_portal", args=["maturity-new-token"]))
        self.assertEqual(new_response.status_code, 200)
