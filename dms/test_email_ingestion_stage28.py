import json
import shutil
import tempfile
from email.message import EmailMessage
from email.utils import format_datetime

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from dms.models import Department, Document, ExternalReference, IntegrationProvider, Organization, User
from dms.services.email_ingestion import EmailIngestionError, ingest_email_message
from dms.services.integrations import create_integration_connection, create_integration_sync_job


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_email_ingestion_media_")


def _noop_indexer(document):
    return False


def _empty_text_extractor(path):
    return ""


def build_email(*, message_id="<message-28@example.test>", filename="contract.txt", payload=b"contract payload"):
    message = EmailMessage()
    message["From"] = "supplier@example.test"
    message["To"] = "inbound@example.test"
    message["Subject"] = "Supply contract from email"
    message["Message-ID"] = message_id
    message["Date"] = format_datetime(timezone.now())
    message.set_content("Please find the attached document.")
    message.add_attachment(
        payload,
        maintype="text",
        subtype="plain",
        filename=filename,
    )
    return message.as_bytes()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class EmailIngestionStage28Tests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="Email ingestion")
        self.other_organization = Organization.objects.create(name="Other Email Org", slug="other-email-org")
        self.other_department = Department.objects.create(
            name="Other Email Department",
            organization=self.other_organization,
        )
        self.user = User.objects.create_user(
            username="email-ingestion-user",
            password="password123",
            department=self.department,
        )
        self.provider = IntegrationProvider.objects.get(code="email")
        self.connection = create_integration_connection(
            organization=self.department.organization,
            provider=self.provider,
            name="Inbound mailbox",
            user=self.user,
            credentials_metadata={"auth_method": "secret_ref"},
            secret_ref="env:EMAIL_INGESTION_PASSWORD",
            settings={"mailbox": "inbound@example.test"},
        )

    def ingest(self, raw_message):
        sync_job = create_integration_sync_job(
            connection=self.connection,
            user=self.user,
            metadata={"source": "test"},
        )
        return ingest_email_message(
            raw_message=raw_message,
            connection=self.connection,
            department=self.department,
            uploaded_by=self.user,
            sync_job=sync_job,
            run_ai=False,
            text_extractor=_empty_text_extractor,
            indexer=_noop_indexer,
        )

    def test_email_attachment_creates_document_version_and_external_reference(self):
        result = self.ingest(build_email())

        self.assertEqual(result.total_attachments, 1)
        self.assertEqual(result.created_documents, 1)
        document = Document.objects.get(source_system="email_ingestion")
        self.assertEqual(document.organization, self.department.organization)
        self.assertEqual(document.department, self.department)
        self.assertEqual(document.versions.count(), 1)
        reference = ExternalReference.objects.get(document=document)
        self.assertEqual(reference.external_type, "email_attachment")
        self.assertEqual(reference.metadata["message_id"], "<message-28@example.test>")
        self.assertEqual(reference.metadata["sender"], "supplier@example.test")
        self.assertEqual(reference.metadata["subject"], "Supply contract from email")
        self.assertEqual(reference.metadata["mailbox"], "inbound@example.test")

    def test_duplicate_message_attachment_does_not_create_duplicate_document(self):
        raw_message = build_email(message_id="<duplicate-message@example.test>")

        first = self.ingest(raw_message)
        second = self.ingest(raw_message)

        self.assertEqual(first.created_documents, 1)
        self.assertEqual(second.created_documents, 0)
        self.assertEqual(second.skipped_duplicates, 1)
        self.assertEqual(Document.objects.filter(source_system="email_ingestion").count(), 1)
        self.assertEqual(ExternalReference.objects.count(), 1)

    def test_unsafe_attachment_is_rejected(self):
        result = self.ingest(
            build_email(
                message_id="<unsafe-message@example.test>",
                filename="malware.exe",
                payload=b"not really executable",
            )
        )

        self.assertEqual(result.created_documents, 0)
        self.assertEqual(result.rejected_attachments, 1)
        self.assertFalse(Document.objects.exists())
        self.assertFalse(ExternalReference.objects.exists())

    def test_organization_isolation_is_preserved(self):
        with self.assertRaises(EmailIngestionError):
            ingest_email_message(
                raw_message=build_email(message_id="<cross-org@example.test>"),
                connection=self.connection,
                department=self.other_department,
                uploaded_by=self.user,
                run_ai=False,
                text_extractor=_empty_text_extractor,
                indexer=_noop_indexer,
            )

        self.assertFalse(Document.objects.exists())
        self.assertFalse(ExternalReference.objects.exists())

    def test_credentials_are_not_stored_in_plaintext_json(self):
        with self.assertRaises(ValidationError):
            create_integration_connection(
                organization=self.department.organization,
                provider=self.provider,
                name="Unsafe mailbox",
                user=self.user,
                credentials_metadata={"password": "plain-text-password"},
            )

        self.ingest(build_email(message_id="<safe-metadata@example.test>"))
        payload = json.dumps(
            {
                "connection_metadata": self.connection.credentials_metadata,
                "connection_settings": self.connection.settings,
                "external_reference_metadata": list(ExternalReference.objects.values_list("metadata", flat=True)),
            }
        )
        self.assertNotIn("plain-text-password", payload)
        self.assertNotIn("env:EMAIL_INGESTION_PASSWORD", payload)
