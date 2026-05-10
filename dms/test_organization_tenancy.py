import shutil
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import (
    Department,
    Document,
    DocumentAccess,
    DocumentActivity,
    Folder,
    Organization,
    OrganizationMember,
    User,
)
from dms.utils import get_allowed_departments, get_allowed_documents


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_tenancy_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class OrganizationTenantIsolationTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.org_a = Organization.objects.create(name="Tenant A", slug="tenant-a")
        self.org_b = Organization.objects.create(name="Tenant B", slug="tenant-b")
        self.department_a = Department.objects.create(
            organization=self.org_a,
            name="Archive",
        )
        self.department_b = Department.objects.create(
            organization=self.org_b,
            name="Archive",
        )
        self.user_a = User.objects.create_user(
            username="tenant-a-user",
            password="password123",
            department=self.department_a,
        )
        self.user_b = User.objects.create_user(
            username="tenant-b-user",
            password="password123",
            department=self.department_b,
        )
        self.admin_a = User.objects.create_user(
            username="tenant-a-admin",
            password="password123",
            role=User.Role.ADMIN,
        )
        OrganizationMember.objects.create(
            organization=self.org_a,
            user=self.user_a,
            role=OrganizationMember.Role.MEMBER,
        )
        OrganizationMember.objects.create(
            organization=self.org_b,
            user=self.user_b,
            role=OrganizationMember.Role.MEMBER,
        )
        OrganizationMember.objects.create(
            organization=self.org_a,
            user=self.admin_a,
            role=OrganizationMember.Role.ADMIN,
        )
        self.document_a = Document.objects.create(
            organization=self.org_a,
            department=self.department_a,
            title="Tenant A document",
            file=SimpleUploadedFile("tenant-a.txt", b"tenant a"),
            uploaded_by=self.user_a,
        )
        self.document_b = Document.objects.create(
            organization=self.org_b,
            department=self.department_b,
            title="Tenant B document",
            file=SimpleUploadedFile("tenant-b.txt", b"tenant b"),
            uploaded_by=self.user_b,
        )

    def test_allowed_documents_are_limited_by_organization(self):
        DocumentAccess.objects.create(
            document=self.document_b,
            department=self.department_a,
            granted_by=self.user_b,
        )

        documents = get_allowed_documents(self.user_a)

        self.assertIn(self.document_a, documents)
        self.assertNotIn(self.document_b, documents)

    def test_admin_sees_only_member_organization_departments(self):
        departments = get_allowed_departments(self.admin_a)
        documents = get_allowed_documents(self.admin_a)

        self.assertIn(self.department_a, departments)
        self.assertNotIn(self.department_b, departments)
        self.assertIn(self.document_a, documents)
        self.assertNotIn(self.document_b, documents)

    @patch("dms.views.index_document")
    @patch("dms.views.parse_document")
    @patch("dms.views.extract_text_from_file")
    def test_upload_assigns_document_to_user_organization(
        self,
        extract_text_mock,
        parse_document_mock,
        index_document_mock,
    ):
        extract_text_mock.return_value = "tenant upload text"
        parse_document_mock.return_value = {}
        index_document_mock.return_value = False
        self.client.force_login(self.user_a)

        response = self.client.post(
            reverse("dms:document_upload"),
            {
                "title": "Tenant upload",
                "status": Document.Status.DRAFT,
                "new_folder": "Incoming",
                "file": SimpleUploadedFile("tenant-upload.txt", b"upload"),
            },
        )

        self.assertEqual(response.status_code, 302)
        document = Document.objects.get(title="Tenant upload")
        self.assertEqual(document.organization, self.org_a)
        self.assertEqual(document.department, self.department_a)
        self.assertTrue(Folder.objects.filter(name="Incoming", organization=self.org_a).exists())
        self.assertTrue(
            DocumentActivity.objects.filter(
                document=document,
                action=DocumentActivity.ACTION_UPLOADED,
            ).exists()
        )
