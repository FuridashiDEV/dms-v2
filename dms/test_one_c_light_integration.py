import json
import shutil
import tempfile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from dms.models import Department, Document, ExternalReference, ExtractedField, IntegrationProvider, Organization, ProcessingJob, User
from dms.services.integrations import create_integration_connection, create_integration_sync_job
from dms.services.one_c_light import OneCLightError, build_1c_light_export_payload, import_1c_light_document


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_1c_light_media_")


def _noop_indexer(document):
    return False


def _empty_text_extractor(path):
    return ""


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class OneCLightIntegrationTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="1C department")
        self.other_organization = Organization.objects.create(name="Other 1C Org", slug="other-1c-org")
        self.other_department = Department.objects.create(
            name="Other 1C Department",
            organization=self.other_organization,
        )
        self.user = User.objects.create_user(
            username="one-c-user",
            password="password123",
            department=self.department,
        )
        self.provider = IntegrationProvider.objects.get(code="1c")
        self.connection = create_integration_connection(
            organization=self.department.organization,
            provider=self.provider,
            name="1C Light",
            user=self.user,
            credentials_metadata={"auth_method": "secret_ref"},
            secret_ref="env:ONE_C_LIGHT_TOKEN",
        )

    def import_payload(self, *, external_id="1c-doc-001", file_name="invoice.json", content=b'{"number":"A-001"}'):
        sync_job = create_integration_sync_job(
            connection=self.connection,
            user=self.user,
            metadata={"source": "test"},
        )
        return import_1c_light_document(
            uploaded_file=SimpleUploadedFile(file_name, content, content_type="application/json"),
            connection=self.connection,
            department=self.department,
            external_id=external_id,
            object_type="invoice",
            title="1C invoice",
            metadata={"document_number": "A-001"},
            uploaded_by=self.user,
            sync_job=sync_job,
            run_ai=False,
            text_extractor=_empty_text_extractor,
            indexer=_noop_indexer,
        )

    def test_1c_provider_exists(self):
        self.assertEqual(self.provider.provider_type, IntegrationProvider.ProviderType.ONE_C)
        self.assertTrue(self.provider.is_active)

    def test_import_creates_document_version_and_external_reference(self):
        result = self.import_payload()

        self.assertEqual(result.status, "created")
        document = Document.objects.get(pk=result.document_id)
        self.assertEqual(document.source_system, "1c_light")
        self.assertEqual(document.organization, self.department.organization)
        self.assertEqual(document.versions.count(), 1)
        reference = ExternalReference.objects.get(pk=result.external_reference_id)
        self.assertEqual(reference.document, document)
        self.assertEqual(reference.provider, self.provider)
        self.assertEqual(reference.external_id, "1c-doc-001")
        self.assertEqual(reference.external_type, "invoice")
        self.assertEqual(reference.metadata["source"], "1c_light")
        self.assertEqual(reference.metadata["document_number"], "A-001")

    def test_duplicate_external_id_does_not_create_duplicate_document(self):
        first = self.import_payload(external_id="duplicate-1c-id")
        second = self.import_payload(external_id="duplicate-1c-id")

        self.assertEqual(first.status, "created")
        self.assertEqual(second.status, "duplicate")
        self.assertEqual(Document.objects.filter(source_system="1c_light").count(), 1)
        self.assertEqual(ExternalReference.objects.count(), 1)

    def test_export_includes_confirmed_fields_only(self):
        result = self.import_payload(external_id="export-1c-id")
        document = Document.objects.get(pk=result.document_id)
        job = ProcessingJob.objects.create(
            organization=document.organization,
            document=document,
            created_by=self.user,
            source=ProcessingJob.Source.MANUAL,
            status=ProcessingJob.Status.COMPLETED,
        )
        ExtractedField.objects.create(
            organization=document.organization,
            job=job,
            document=document,
            field_name="counterparty",
            label="Counterparty",
            value="Confirmed Supplier LLP",
            status=ExtractedField.Status.CONFIRMED,
            reviewed_by=self.user,
            reviewed_at=timezone.now(),
        )
        ExtractedField.objects.create(
            organization=document.organization,
            job=job,
            document=document,
            field_name="amount",
            label="Amount",
            value="100000",
            status=ExtractedField.Status.APPLIED,
            reviewed_by=self.user,
            reviewed_at=timezone.now(),
            applied_at=timezone.now(),
        )
        ExtractedField.objects.create(
            organization=document.organization,
            job=job,
            document=document,
            field_name="title",
            label="Title",
            value="Unconfirmed AI title",
            status=ExtractedField.Status.SUGGESTED,
        )

        payload = build_1c_light_export_payload(document=document, connection=self.connection)

        self.assertEqual(payload["export_scope"], "confirmed_or_applied_fields_only")
        self.assertIn("counterparty", payload["confirmed_fields"])
        self.assertIn("amount", payload["confirmed_fields"])
        self.assertNotIn("title", payload["confirmed_fields"])
        serialized = json.dumps(payload)
        self.assertNotIn("Unconfirmed AI title", serialized)

    def test_plaintext_credentials_are_rejected(self):
        with self.assertRaises(ValidationError):
            create_integration_connection(
                organization=self.department.organization,
                provider=self.provider,
                name="Unsafe 1C",
                user=self.user,
                credentials_metadata={"access_token": "plain-token"},
            )

    def test_organization_isolation_is_preserved(self):
        with self.assertRaises(OneCLightError):
            import_1c_light_document(
                uploaded_file=SimpleUploadedFile("blocked.json", b"{}", content_type="application/json"),
                connection=self.connection,
                department=self.other_department,
                external_id="cross-org-1c",
                uploaded_by=self.user,
                run_ai=False,
                text_extractor=_empty_text_extractor,
                indexer=_noop_indexer,
            )

        self.assertFalse(Document.objects.exists())
        self.assertFalse(ExternalReference.objects.exists())
