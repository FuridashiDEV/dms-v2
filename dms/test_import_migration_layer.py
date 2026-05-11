import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import AuditEvent, Department, Document, ImportBatch, ImportFile, User


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_import_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ImportMigrationLayerTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="Import department")
        self.user = User.objects.create_user(
            username="import-user",
            password="password123",
            department=self.department,
        )

    def test_multiple_file_import_creates_documents_versions_and_audit(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dms:document_import"),
            {
                "department": str(self.department.id),
                "new_folder": "Imported",
                "files": [
                    SimpleUploadedFile("first.txt", b"first payload"),
                    SimpleUploadedFile("second.txt", b"second payload"),
                ],
            },
        )

        batch = ImportBatch.objects.get()
        self.assertRedirects(response, reverse("dms:import_batch_detail", args=[batch.id]))
        self.assertEqual(batch.imported_files, 2)
        self.assertEqual(batch.duplicate_files, 0)
        self.assertEqual(batch.failed_files, 0)
        self.assertEqual(Document.objects.filter(source_system=f"import_batch:{batch.id}").count(), 2)
        for document in Document.objects.filter(source_system=f"import_batch:{batch.id}"):
            self.assertEqual(document.organization, self.department.organization)
            self.assertEqual(document.department, self.department)
            self.assertEqual(document.versions.count(), 1)
            self.assertFalse(document.processing_jobs.exists())
        self.assertEqual(ImportFile.objects.filter(status=ImportFile.Status.IMPORTED).count(), 2)
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type=AuditEvent.EventType.IMPORT_BATCH_CREATED,
                metadata__import_batch_id=batch.id,
            ).exists()
        )
        self.assertEqual(
            AuditEvent.objects.filter(event_type=AuditEvent.EventType.IMPORT_FILE_IMPORTED).count(),
            2,
        )

    def test_duplicate_import_is_detected_by_checksum_in_organization(self):
        existing = Document.objects.create(
            department=self.department,
            title="Existing",
            file=SimpleUploadedFile("existing.txt", b"same payload"),
            uploaded_by=self.user,
        )
        existing.checksum_sha256 = "e94045d2493922f0ce901226bf668cfe954f6b503bfab1fef09370af7e972812"
        existing.save(update_fields=["checksum_sha256"])
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dms:document_import"),
            {
                "department": str(self.department.id),
                "new_folder": "Imported",
                "files": [SimpleUploadedFile("duplicate.txt", b"same payload")],
            },
        )

        batch = ImportBatch.objects.get()
        self.assertRedirects(response, reverse("dms:import_batch_detail", args=[batch.id]))
        self.assertEqual(batch.imported_files, 0)
        self.assertEqual(batch.duplicate_files, 1)
        import_file = ImportFile.objects.get()
        self.assertEqual(import_file.status, ImportFile.Status.DUPLICATE)
        self.assertEqual(import_file.duplicate_of, existing)
        self.assertEqual(Document.objects.count(), 1)
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type=AuditEvent.EventType.IMPORT_FILE_DUPLICATE,
                document=existing,
                metadata__import_file_id=import_file.id,
            ).exists()
        )

    def test_employee_cannot_import_to_unavailable_department(self):
        other_department = Department.objects.create(name="Other import")
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dms:document_import"),
            {
                "department": str(other_department.id),
                "new_folder": "Imported",
                "files": [SimpleUploadedFile("blocked.txt", b"blocked")],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ImportBatch.objects.exists())
        self.assertFalse(Document.objects.exists())
