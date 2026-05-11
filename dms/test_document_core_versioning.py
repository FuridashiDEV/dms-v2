import hashlib
import shutil
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import Department, Document, Folder, User
from dms.services.preservation import calculate_file_sha256


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_document_core_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class DocumentCoreVersioningTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="Document core")
        self.user = User.objects.create_user(
            username="document-core-user",
            password="password123",
            department=self.department,
        )

    def test_calculate_file_sha256_reads_django_uploaded_file(self):
        uploaded_file = SimpleUploadedFile("checksum.txt", b"checksum-payload")

        checksum = calculate_file_sha256(uploaded_file)

        self.assertEqual(
            checksum,
            hashlib.sha256(b"checksum-payload").hexdigest(),
        )

    @patch("dms.views.index_document")
    @patch("dms.views.parse_document")
    @patch("dms.views.extract_text_from_file")
    def test_upload_creates_initial_version_with_checksum_and_organization(
        self,
        extract_text_mock,
        parse_document_mock,
        index_document_mock,
    ):
        extract_text_mock.return_value = "uploaded text"
        parse_document_mock.return_value = {}
        index_document_mock.return_value = False
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dms:document_upload"),
            {
                "title": "Versioned upload",
                "status": Document.Status.APPROVED,
                "new_folder": "Incoming",
                "file": SimpleUploadedFile("upload.txt", b"upload-payload"),
            },
        )

        self.assertEqual(response.status_code, 302)
        document = Document.objects.get(title="Versioned upload")
        version = document.versions.get(number=1)
        expected_checksum = hashlib.sha256(b"upload-payload").hexdigest()

        self.assertEqual(document.checksum_sha256, expected_checksum)
        self.assertEqual(version.checksum_sha256, expected_checksum)
        self.assertEqual(version.organization, document.organization)
        self.assertEqual(version.status, Document.Status.APPROVED)
        self.assertEqual(version.file.name, document.file.name)
        self.assertTrue(
            Folder.objects.filter(
                name="Incoming",
                organization=document.organization,
                department=document.department,
            ).exists()
        )

    def test_create_version_computes_checksum_for_legacy_document_snapshot(self):
        document = Document.objects.create(
            department=self.department,
            title="Legacy document",
            file=SimpleUploadedFile("legacy.txt", b"legacy-payload"),
            uploaded_by=self.user,
        )
        document.checksum_sha256 = ""
        document.save(update_fields=["checksum_sha256"])

        version = document.create_version(uploaded_by=self.user)

        self.assertEqual(version.organization, document.organization)
        self.assertEqual(
            version.checksum_sha256,
            hashlib.sha256(b"legacy-payload").hexdigest(),
        )
