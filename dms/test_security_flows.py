import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import Department, Document, DocumentAccess, User


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_security_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class DocumentAccessManagementTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="Access owner")
        self.sub_department = Department.objects.create(
            name="Access child",
            parent=self.department,
        )
        self.outsider_department = Department.objects.create(name="Access outsider")

        self.owner = User.objects.create_user(
            username="access-owner",
            password="password123",
            department=self.department,
        )
        self.outsider = User.objects.create_user(
            username="access-outsider",
            password="password123",
            department=self.outsider_department,
        )

        self.document = Document.objects.create(
            department=self.department,
            title="Access controlled document",
            file=SimpleUploadedFile("access.txt", b"access"),
            uploaded_by=self.owner,
        )
        self.access = DocumentAccess.objects.create(
            document=self.document,
            department=self.sub_department,
            granted_by=self.owner,
        )

    def test_owner_can_revoke_access_via_post(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("dms:document_access_revoke", args=[self.access.id])
        )

        self.assertRedirects(
            response,
            reverse("dms:document_access_manage", args=[self.document.id]),
        )
        self.assertFalse(DocumentAccess.objects.filter(id=self.access.id).exists())

    def test_get_revoke_is_not_allowed(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("dms:document_access_revoke", args=[self.access.id])
        )

        self.assertEqual(response.status_code, 405)
        self.assertTrue(DocumentAccess.objects.filter(id=self.access.id).exists())

    def test_outsider_cannot_revoke_access(self):
        self.client.force_login(self.outsider)

        response = self.client.post(
            reverse("dms:document_access_revoke", args=[self.access.id])
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(DocumentAccess.objects.filter(id=self.access.id).exists())


class AuthenticationSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="rate-limited-user",
            password="password123",
        )

    def test_login_is_rate_limited_after_repeated_failures(self):
        for _ in range(5):
            response = self.client.post(
                reverse("login"),
                {"username": self.user.username, "password": "wrong-password"},
            )
            self.assertEqual(response.status_code, 200)

        blocked = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": "wrong-password"},
        )

        self.assertEqual(blocked.status_code, 200)
        self.assertContains(blocked, "Слишком много попыток входа")
