import io
import shutil
import tempfile
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.forms import validate_uploaded_file
from dms.models import AuditEvent, Counterparty, Department, Document, Organization, User
from dms.services.counterparty import create_document_exchange


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_stage32_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class EnterpriseSecurityStage32Tests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="Security stage32")
        self.other_organization = Organization.objects.create(
            name="Other Security Org",
            slug="other-security-org",
        )
        self.other_department = Department.objects.create(
            name="Other Security Department",
            organization=self.other_organization,
        )
        self.admin = User.objects.create_user(
            username="security-admin",
            password="password123",
            role=User.Role.ADMIN,
            department=self.department,
        )
        self.employee = User.objects.create_user(
            username="security-employee",
            password="password123",
            role=User.Role.EMPLOYEE,
            department=self.department,
        )
        self.other_admin = User.objects.create_user(
            username="other-security-admin",
            password="password123",
            role=User.Role.ADMIN,
            department=self.other_department,
        )
        self.document = Document.objects.create(
            department=self.department,
            title="Security controls document",
            file=SimpleUploadedFile("security.txt", b"security payload", content_type="text/plain"),
            uploaded_by=self.admin,
        )

    def test_security_settings_validation_does_not_expose_secrets(self):
        stdout = io.StringIO()
        secret = "stage32-super-secret-value"

        with override_settings(DEBUG=True, SECRET_KEY=secret):
            with self.assertRaises(SystemExit):
                call_command("validate_production_security", stdout=stdout)

        output = stdout.getvalue()
        self.assertIn("debug_enabled", output)
        self.assertNotIn(secret, output)
        self.assertNotIn("POSTGRES_PASSWORD", output)

    def test_audit_export_is_access_controlled_and_redacts_metadata(self):
        AuditEvent.objects.create(
            organization=self.department.organization,
            user=self.admin,
            document=self.document,
            event_type=AuditEvent.EventType.DOCUMENT_DOWNLOADED,
            metadata={
                "document_id": self.document.id,
                "secure_token": "raw-token",
                "nested": {"api_key": "raw-api-key"},
                "safe": "visible",
            },
        )
        self.client.force_login(self.admin)

        allowed_response = self.client.get(
            reverse("dms:security_audit_export"),
            {"organization": self.department.organization_id},
        )
        denied_response = self.client.get(
            reverse("dms:security_audit_export"),
            {"organization": self.other_organization.id},
        )

        self.assertEqual(allowed_response.status_code, 200)
        content = allowed_response.content.decode("utf-8")
        self.assertIn("DOCUMENT_DOWNLOADED", content)
        self.assertIn("visible", content)
        self.assertIn("[redacted]", content)
        self.assertNotIn("raw-token", content)
        self.assertNotIn("raw-api-key", content)
        self.assertEqual(denied_response.status_code, 404)

    @override_settings(DMS_ORGANIZATION_IP_ALLOWLISTS={"default": ["10.10.10.0/24"]})
    def test_ip_allowlist_denies_unauthorized_ip_if_enabled(self):
        self.client.force_login(self.admin)

        denied = self.client.get(reverse("dms:dashboard"), REMOTE_ADDR="192.0.2.10")
        allowed = self.client.get(reverse("dms:dashboard"), REMOTE_ADDR="10.10.10.5")

        self.assertEqual(denied.status_code, 403)
        self.assertIn("IP allowlist", denied.content.decode("utf-8"))
        self.assertEqual(allowed.status_code, 200)
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type="SECURITY_IP_ALLOWLIST_DENIED",
                user=self.admin,
            ).exists()
        )

    @override_settings(DMS_ORGANIZATION_IP_ALLOWLISTS={"default": ["10.10.10.0/24"]})
    def test_normal_login_still_works_with_allowlist_configured(self):
        response = self.client.post(
            reverse("login"),
            {"username": self.admin.username, "password": "password123"},
            REMOTE_ADDR="192.0.2.10",
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type="SECURITY_LOGIN_SUCCESS",
                user=self.admin,
            ).exists()
        )

    def test_file_upload_security_still_works(self):
        with self.assertRaises(ValidationError):
            validate_uploaded_file(
                SimpleUploadedFile(
                    "unsafe.html",
                    b"<script>alert(1)</script>",
                    content_type="text/html",
                )
            )

        def scanner_failure(uploaded_file):
            raise RuntimeError("scanner offline")

        with override_settings(
            DMS_ANTIVIRUS_SCANNER="dms.test_enterprise_security_stage32.scanner_failure",
            DMS_ANTIVIRUS_FAIL_CLOSED=True,
        ):
            with patch("dms.test_enterprise_security_stage32.scanner_failure", scanner_failure, create=True):
                with self.assertRaises(ValidationError):
                    validate_uploaded_file(
                        SimpleUploadedFile("safe.txt", b"payload", content_type="text/plain")
                    )

    def test_portal_token_security_still_works(self):
        counterparty = Counterparty.objects.create(
            organization=self.department.organization,
            name="Stage32 Counterparty",
            created_by=self.admin,
        )
        created = create_document_exchange(
            document=self.document,
            counterparty=counterparty,
            user=self.admin,
            message="Security portal check",
        )

        invalid_response = self.client.get(reverse("dms:counterparty_portal", args=["not-a-valid-token"]))
        download_response = self.client.get(
            reverse("dms:counterparty_portal_download", args=[created.token])
        )

        self.assertEqual(invalid_response.status_code, 404)
        self.assertEqual(download_response.status_code, 200)
        event = AuditEvent.objects.filter(
            document=self.document,
            event_type=AuditEvent.EventType.EXCHANGE_DOWNLOADED,
        ).latest("created_at")
        self.assertNotIn(created.token, str(event.metadata))

    def test_employee_cannot_access_security_dashboard(self):
        self.client.force_login(self.employee)

        dashboard_response = self.client.get(reverse("dms:security_dashboard"))
        export_response = self.client.get(reverse("dms:security_audit_export"))

        self.assertEqual(dashboard_response.status_code, 403)
        self.assertEqual(export_response.status_code, 403)
