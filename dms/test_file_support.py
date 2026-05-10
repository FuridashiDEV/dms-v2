import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from dms.forms import DocumentUploadForm
from dms.models import Department, Document, Folder, User
from dms.services.text_extractor import extract_text_from_file


class DocumentUploadArchiveSupportTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Archive support")
        self.user = User.objects.create_user(
            username="archive-support",
            password="password123",
            department=self.department,
        )
        self.folder = Folder.objects.create(
            name="Storage",
            department=self.department,
        )

    def test_unknown_file_extension_is_allowed_for_archive_storage(self):
        form = DocumentUploadForm(
            data={
                "department": str(self.department.id),
                "folder": str(self.folder.id),
                "new_folder": "",
                "new_subfolder": "",
                "title": "Binary archive",
                "doc_type": "",
                "status": Document.Status.DRAFT,
                "doc_date": "",
                "description": "desc",
            },
            files={"file": SimpleUploadedFile("archive.zip", b"zip-binary")},
            user=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors)


class TextExtractorSupportTests(TestCase):
    def test_extract_text_from_txt_file(self):
        file_path = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        try:
            file_path.write("Архивный текст".encode("utf-8"))
            file_path.close()

            result = extract_text_from_file(file_path.name)

            self.assertIn("Архивный текст", result)
        finally:
            shutil.os.unlink(file_path.name)

    def test_extract_text_from_csv_file(self):
        file_path = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        try:
            file_path.write("year,title\n2025,Report".encode("utf-8"))
            file_path.close()

            result = extract_text_from_file(file_path.name)

            self.assertIn("2025", result)
            self.assertIn("Report", result)
        finally:
            shutil.os.unlink(file_path.name)
