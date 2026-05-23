import io
import shutil
import tempfile

from django.core.management import call_command
from django.test import TestCase, override_settings

from dms.management.commands.prepare_demo_data import DEMO_ORG_SLUG
from dms.models import (
    AuditEvent,
    Document,
    DocumentExchange,
    DocumentRelation,
    DocumentType,
    ExchangeMessage,
    ExtractedField,
    Folder,
    ImportBatch,
    ImportFile,
    Organization,
    ProcessingJob,
    UsageEvent,
    WorkflowInstance,
)
from dms.test_factories import make_document, make_org_context


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_demo_data_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class PrepareDemoDataCommandTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def test_prepare_demo_data_is_idempotent_and_keeps_non_demo_data(self):
        other_context = make_org_context(slug="non-demo-org", username="non-demo-user")
        other_document = make_document(context=other_context, title="Non-demo document")

        first_output = io.StringIO()
        call_command("prepare_demo_data", skip_vectors=True, stdout=first_output)
        first_counts = self._demo_counts()

        second_output = io.StringIO()
        call_command("prepare_demo_data", skip_vectors=True, stdout=second_output)
        second_counts = self._demo_counts()

        self.assertEqual(first_counts, second_counts)
        self.assertEqual(
            second_counts,
            {
                "documents": 13,
                "document_versions": 14,
                "document_types": 10,
                "folders": 12,
                "relations": 10,
                "processing_jobs": 1,
                "extracted_fields": 4,
                "workflow_instances": 2,
                "exchanges": 2,
                "messages": 2,
                "import_batches": 1,
                "import_files": 3,
                "audit_events": 14,
                "usage_events": 18,
            },
        )
        self.assertIn("demo_admin / DemoArchive2026!", second_output.getvalue())
        self.assertIn("External portal demo URL path: /portal/exchanges/", second_output.getvalue())
        self.assertTrue(
            Document.objects.filter(
                pk=other_document.pk,
                organization=other_context.organization,
                title="Non-demo document",
            ).exists()
        )

    def _demo_counts(self) -> dict[str, int]:
        organization = Organization.objects.get(slug=DEMO_ORG_SLUG)
        documents = Document.objects.filter(organization=organization)
        return {
            "documents": documents.count(),
            "document_versions": sum(document.versions.count() for document in documents),
            "document_types": DocumentType.objects.filter(organization=organization).count(),
            "folders": Folder.objects.filter(organization=organization).count(),
            "relations": DocumentRelation.objects.filter(from_document__organization=organization).count(),
            "processing_jobs": ProcessingJob.objects.filter(organization=organization).count(),
            "extracted_fields": ExtractedField.objects.filter(organization=organization).count(),
            "workflow_instances": WorkflowInstance.objects.filter(organization=organization).count(),
            "exchanges": DocumentExchange.objects.filter(organization=organization).count(),
            "messages": ExchangeMessage.objects.filter(organization=organization).count(),
            "import_batches": ImportBatch.objects.filter(organization=organization).count(),
            "import_files": ImportFile.objects.filter(organization=organization).count(),
            "audit_events": AuditEvent.objects.filter(organization=organization).count(),
            "usage_events": UsageEvent.objects.filter(organization=organization).count(),
        }
