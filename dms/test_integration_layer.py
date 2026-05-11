import json
import shutil
import tempfile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from dms.models import (
    AuditEvent,
    Department,
    Document,
    ExternalReference,
    IntegrationConnection,
    IntegrationProvider,
    Organization,
    UsageEvent,
    User,
)
from dms.services.integrations import (
    IntegrationError,
    create_integration_connection,
    create_integration_sync_job,
    link_external_reference,
)


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_integration_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class IntegrationLayerTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="Integration department")
        self.other_organization = Organization.objects.create(
            name="Other Integration Org",
            slug="other-integration-org",
        )
        self.other_department = Department.objects.create(
            name="Other integration department",
            organization=self.other_organization,
        )
        self.user = User.objects.create_user(
            username="integration-user",
            password="password123",
            department=self.department,
        )
        self.document = Document.objects.create(
            department=self.department,
            title="Integration document",
            file=SimpleUploadedFile("integration.txt", b"integration payload"),
            uploaded_by=self.user,
        )
        self.other_document = Document.objects.create(
            department=self.other_department,
            title="Other integration document",
            file=SimpleUploadedFile("other-integration.txt", b"other integration payload"),
        )
        self.provider = IntegrationProvider.objects.get(code="email")

    def test_standard_providers_are_seeded(self):
        provider_codes = set(IntegrationProvider.objects.values_list("code", flat=True))

        self.assertTrue(
            {"email", "1c", "google-drive", "onedrive", "sharepoint", "external-api", "erp"}.issubset(
                provider_codes
            )
        )

    def test_connection_rejects_plaintext_secret_metadata(self):
        with self.assertRaises(ValidationError):
            create_integration_connection(
                organization=self.department.organization,
                provider=self.provider,
                name="Unsafe email",
                user=self.user,
                credentials_metadata={"access_token": "do-not-store"},
            )

        with self.assertRaises(ValidationError):
            create_integration_connection(
                organization=self.department.organization,
                provider=self.provider,
                name="Unsafe ref",
                user=self.user,
                secret_ref="token=do-not-store",
            )

    def test_external_reference_links_existing_document_and_records_events(self):
        connection = create_integration_connection(
            organization=self.department.organization,
            provider="email",
            name="Inbound email",
            user=self.user,
            credentials_metadata={"auth_method": "secret_ref"},
            secret_ref="vault://integrations/email/inbound",
        )
        sync_job = create_integration_sync_job(
            connection=connection,
            user=self.user,
            metadata={"source": "manual-test"},
        )

        reference = link_external_reference(
            document=self.document,
            connection=connection,
            sync_job=sync_job,
            external_id="message-123",
            external_type="email_message",
            display_name="Supplier contract email",
            metadata={"mailbox": "contracts@example.test"},
            user=self.user,
        )

        self.assertEqual(reference.document, self.document)
        self.assertEqual(reference.organization, self.department.organization)
        self.assertEqual(reference.provider, self.provider)
        self.assertEqual(reference.connection, connection)
        sync_job.refresh_from_db()
        self.assertEqual(sync_job.linked_references, 1)
        self.assertTrue(
            AuditEvent.objects.filter(
                organization=self.department.organization,
                document=self.document,
                event_type=AuditEvent.EventType.EXTERNAL_REFERENCE_LINKED,
                metadata__external_reference_id=reference.id,
            ).exists()
        )
        self.assertTrue(
            UsageEvent.objects.filter(
                organization=self.department.organization,
                document=self.document,
                event_type=UsageEvent.EventType.EXTERNAL_REFERENCE_LINKED,
                metadata__external_reference_id=reference.id,
            ).exists()
        )

    def test_external_reference_rejects_cross_organization_document(self):
        connection = create_integration_connection(
            organization=self.department.organization,
            provider=self.provider,
            name="Scoped email",
            user=self.user,
        )

        with self.assertRaises(IntegrationError):
            link_external_reference(
                document=self.other_document,
                connection=connection,
                external_id="cross-org-1",
                external_type="email_message",
                user=self.user,
            )

        self.assertFalse(ExternalReference.objects.filter(external_id="cross-org-1").exists())

    def test_usage_metadata_does_not_leak_secret_values(self):
        connection = create_integration_connection(
            organization=self.department.organization,
            provider=self.provider,
            name="Safe email",
            user=self.user,
            credentials_metadata={"auth_method": "secret_ref"},
            secret_ref="vault://integrations/email/safe",
        )

        payload = json.dumps(list(UsageEvent.objects.filter(organization=connection.organization).values("metadata")))
        self.assertNotIn("vault://integrations/email/safe", payload)
