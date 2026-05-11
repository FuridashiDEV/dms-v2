import shutil
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import AuditEvent, Department, Document, ExtractedField, ProcessingJob, User


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_ai_processing_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AiProcessingPipelineTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="AI processing")
        self.user = User.objects.create_user(
            username="ai-reviewer",
            password="password123",
            department=self.department,
        )

    @patch("dms.views.index_document")
    @patch("dms.views.parse_document")
    @patch("dms.views.extract_text_from_file")
    def test_upload_saves_ai_suggestions_without_applying_to_document(
        self,
        extract_text_mock,
        parse_document_mock,
        index_document_mock,
    ):
        extract_text_mock.return_value = "15.01.2025 Договор поставки"
        parse_document_mock.return_value = {
            "title_ru": "AI title",
            "summary_ru": "AI summary",
            "doc_type": "Договор",
            "date_index": 0,
            "document_author": "AI author",
            "language": "RU",
            "retention_category": "Договорной документ",
            "legal_hold": True,
        }
        index_document_mock.return_value = False
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dms:document_upload"),
            {
                "title": "Manual title",
                "status": Document.Status.DRAFT,
                "new_folder": "AI inbox",
                "file": SimpleUploadedFile("ai.txt", b"ai"),
            },
        )

        self.assertEqual(response.status_code, 302)
        document = Document.objects.get(title="Manual title")
        self.assertIsNone(document.doc_date)
        self.assertIsNone(document.doc_type)
        self.assertEqual(document.document_author, "")

        job = document.processing_jobs.get()
        self.assertEqual(job.status, ProcessingJob.Status.COMPLETED)
        self.assertEqual(job.source, ProcessingJob.Source.UPLOAD)
        self.assertEqual(job.fields.get(field_name="title").value, "AI title")
        self.assertEqual(job.fields.get(field_name="doc_date").value, "2025-01-15")
        self.assertTrue(
            AuditEvent.objects.filter(
                document=document,
                event_type=AuditEvent.EventType.AI_PROCESSING_COMPLETED,
                metadata__processing_job_id=job.id,
            ).exists()
        )

    @patch("dms.views.index_document")
    @patch("dms.views.parse_document")
    @patch("dms.views.extract_text_from_file")
    def test_ai_review_confirms_edits_and_applies_only_confirmed_fields(
        self,
        extract_text_mock,
        parse_document_mock,
        index_document_mock,
    ):
        extract_text_mock.return_value = "15.01.2025 Договор поставки"
        parse_document_mock.return_value = {
            "title_ru": "AI title",
            "summary_ru": "AI summary",
            "doc_type": "Договор",
            "date_index": 0,
            "language": "RU",
            "legal_hold": False,
        }
        index_document_mock.return_value = False
        self.client.force_login(self.user)
        self.client.post(
            reverse("dms:document_upload"),
            {
                "title": "Manual title",
                "status": Document.Status.DRAFT,
                "new_folder": "AI inbox",
                "file": SimpleUploadedFile("ai-apply.txt", b"ai"),
            },
        )
        document = Document.objects.get(title="Manual title")
        job = document.processing_jobs.get()

        payload = {"action": "apply"}
        for field in job.fields.all():
            payload[f"field_{field.id}"] = field.value
            payload[f"decision_{field.id}"] = "reject"

        title_field = job.fields.get(field_name="title")
        date_field = job.fields.get(field_name="doc_date")
        doc_type_field = job.fields.get(field_name="doc_type")
        payload[f"field_{title_field.id}"] = "Reviewed title"
        payload[f"decision_{title_field.id}"] = "confirm"
        payload[f"decision_{date_field.id}"] = "confirm"
        payload[f"decision_{doc_type_field.id}"] = "confirm"

        response = self.client.post(
            reverse("dms:document_ai_review", args=[document.id]),
            payload,
        )

        self.assertRedirects(response, reverse("dms:document_detail", args=[document.id]))
        document.refresh_from_db()
        self.assertEqual(document.title, "Reviewed title")
        self.assertEqual(document.doc_date.isoformat(), "2025-01-15")
        self.assertEqual(document.doc_type.name, "Договор")
        self.assertEqual(document.description, "")
        self.assertEqual(
            job.fields.get(field_name="title").status,
            ExtractedField.Status.APPLIED,
        )
        self.assertEqual(
            job.fields.get(field_name="description").status,
            ExtractedField.Status.REJECTED,
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                document=document,
                event_type=AuditEvent.EventType.AI_FIELDS_APPLIED,
                metadata__applied_fields__contains=["title"],
            ).exists()
        )

    def test_user_without_manage_rights_cannot_review_ai_fields(self):
        other_department = Department.objects.create(name="Other AI")
        outsider = User.objects.create_user(
            username="ai-outsider",
            password="password123",
            department=other_department,
        )
        document = Document.objects.create(
            department=self.department,
            title="Protected AI",
            file=SimpleUploadedFile("protected.txt", b"protected"),
            uploaded_by=self.user,
        )
        ProcessingJob.objects.create(
            organization=document.organization,
            document=document,
            created_by=self.user,
            status=ProcessingJob.Status.COMPLETED,
        )
        self.client.force_login(outsider)

        response = self.client.get(reverse("dms:document_ai_review", args=[document.id]))

        self.assertEqual(response.status_code, 404)
