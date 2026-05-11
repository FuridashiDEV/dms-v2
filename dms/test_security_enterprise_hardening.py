import hashlib
import shutil
import tempfile
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.forms import validate_uploaded_file
from dms.models import AuditEvent, Counterparty, Department, Document, DocumentExchange, User


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_security_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class SecurityEnterpriseHardeningTests(TestCase):
    token = "stage13-secure-token"

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="Security department")
        self.other_department = Department.objects.create(name="Security other")
        self.user = User.objects.create_user(
            username="security-user",
            password="password123",
            department=self.department,
        )
        self.outsider = User.objects.create_user(
            username="security-outsider",
            password="password123",
            department=self.other_department,
        )
        self.document = Document.objects.create(
            department=self.department,
            title="Security document",
            file=SimpleUploadedFile("security.txt", b"security payload", content_type="text/plain"),
            uploaded_by=self.user,
        )
        self.version = self.document.create_version(uploaded_by=self.user)

    def test_upload_validation_blocks_double_extension_and_dangerous_mime(self):
        with self.assertRaises(ValidationError):
            validate_uploaded_file(
                SimpleUploadedFile(
                    "contract.pdf.exe",
                    b"blocked",
                    content_type="application/pdf",
                )
            )

        with self.assertRaises(ValidationError):
            validate_uploaded_file(
                SimpleUploadedFile(
                    "page.html",
                    b"<script>alert(1)</script>",
                    content_type="text/html",
                )
            )

    def test_antivirus_hook_can_block_upload_without_dependency(self):
        def scanner(uploaded_file):
            return False, "Blocked by test scanner"

        with override_settings(DMS_ANTIVIRUS_SCANNER="dms.test_security_enterprise_hardening.scanner"):
            with patch("dms.test_security_enterprise_hardening.scanner", scanner, create=True):
                with self.assertRaises(ValidationError):
                    validate_uploaded_file(
                        SimpleUploadedFile("safe.pdf", b"payload", content_type="application/pdf")
                    )

    def test_protected_document_file_responses_include_security_headers(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dms:document_view", args=[self.document.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")

    def test_outsider_cannot_access_document_edit_or_file(self):
        self.client.force_login(self.outsider)

        edit_response = self.client.get(reverse("dms:document_edit", args=[self.document.id]))
        file_response = self.client.get(reverse("dms:document_download", args=[self.document.id]))
        version_response = self.client.get(
            reverse("dms:document_version_download", args=[self.document.id, self.version.id])
        )

        self.assertEqual(edit_response.status_code, 404)
        self.assertEqual(file_response.status_code, 404)
        self.assertEqual(version_response.status_code, 403)

    @patch("dms.services.counterparty.generate_exchange_token")
    def test_counterparty_exchange_does_not_store_or_display_secure_token(self, token_mock):
        token_mock.return_value = self.token
        self.client.force_login(self.user)
        counterparty = Counterparty.objects.create(
            organization=self.department.organization,
            name="Security LLP",
            created_by=self.user,
        )

        send_response = self.client.post(
            reverse("dms:document_exchange_send", args=[self.document.id]),
            {
                "counterparty": str(counterparty.id),
                "message": "Security review",
                "expires_days": "7",
            },
        )
        self.assertRedirects(send_response, reverse("dms:document_detail", args=[self.document.id]))

        exchange = DocumentExchange.objects.get(document=self.document)
        self.assertEqual(exchange.token_hash, hashlib.sha256(self.token.encode("utf-8")).hexdigest())
        audit_event = AuditEvent.objects.get(
            document=self.document,
            event_type=AuditEvent.EventType.EXCHANGE_SENT,
            metadata__document_exchange_id=exchange.id,
        )
        self.assertNotIn(self.token, str(audit_event.metadata))
        self.assertNotIn("portal_url", audit_event.metadata)
        self.assertIn("portal_path", audit_event.metadata)

        detail_response = self.client.get(reverse("dms:document_detail", args=[self.document.id]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertNotContains(detail_response, self.token)
        self.assertNotContains(detail_response, exchange.token_hint)
