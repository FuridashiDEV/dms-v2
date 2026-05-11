import shutil
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import (
    AuditEvent,
    Department,
    Document,
    DocumentAccess,
    DocumentActivity,
    Folder,
    User,
)
from dms.services.audit import record_audit_event


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_audit_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AuditEventTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="Audit")
        self.child_department = Department.objects.create(
            name="Audit child",
            parent=self.department,
        )
        self.user = User.objects.create_user(
            username="audit-user",
            password="password123",
            department=self.department,
        )
        self.folder = Folder.objects.create(
            name="Audit folder",
            department=self.department,
        )
        self.document = Document.objects.create(
            department=self.department,
            folder=self.folder,
            title="Audit document",
            file=SimpleUploadedFile("audit.txt", b"audit-payload"),
            uploaded_by=self.user,
        )
        self.version = self.document.create_version(uploaded_by=self.user)

    def test_record_audit_event_stores_request_context(self):
        request = type(
            "Request",
            (),
            {
                "user": self.user,
                "META": {
                    "HTTP_X_FORWARDED_FOR": "203.0.113.5, 10.0.0.1",
                    "HTTP_USER_AGENT": "AuditBrowser/1.0",
                },
            },
        )()

        event = record_audit_event(
            event_type=AuditEvent.EventType.DOCUMENT_VIEWED,
            request=request,
            document=self.document,
        )

        self.assertEqual(event.organization, self.document.organization)
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.ip_address, "203.0.113.5")
        self.assertEqual(event.user_agent, "AuditBrowser/1.0")
        self.assertEqual(event.metadata["document_id"], self.document.id)

    @patch("dms.views.index_document")
    @patch("dms.views.parse_document")
    @patch("dms.views.extract_text_from_file")
    def test_upload_keeps_document_activity_and_records_audit_event(
        self,
        extract_text_mock,
        parse_document_mock,
        index_document_mock,
    ):
        extract_text_mock.return_value = "audit upload text"
        parse_document_mock.return_value = {}
        index_document_mock.return_value = False
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dms:document_upload"),
            {
                "title": "Audited upload",
                "status": Document.Status.DRAFT,
                "folder": str(self.folder.id),
                "file": SimpleUploadedFile("uploaded.txt", b"uploaded"),
            },
        )

        self.assertEqual(response.status_code, 302)
        document = Document.objects.get(title="Audited upload")
        self.assertTrue(
            DocumentActivity.objects.filter(
                document=document,
                action=DocumentActivity.ACTION_UPLOADED,
            ).exists()
        )
        event = AuditEvent.objects.get(
            document=document,
            event_type=AuditEvent.EventType.DOCUMENT_UPLOADED,
        )
        self.assertEqual(event.organization, document.organization)
        self.assertEqual(event.document_version.number, 1)

    def test_view_download_and_version_download_record_audit_events(self):
        self.client.force_login(self.user)

        self.client.get(reverse("dms:document_view", args=[self.document.id]))
        self.client.get(reverse("dms:document_download", args=[self.document.id]))
        self.client.get(
            reverse(
                "dms:document_version_download",
                args=[self.document.id, self.version.id],
            )
        )

        self.assertTrue(
            AuditEvent.objects.filter(
                document=self.document,
                event_type=AuditEvent.EventType.DOCUMENT_VIEWED,
            ).exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                document=self.document,
                event_type=AuditEvent.EventType.DOCUMENT_DOWNLOADED,
            ).exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                document=self.document,
                document_version=self.version,
                event_type=AuditEvent.EventType.DOCUMENT_VERSION_DOWNLOADED,
            ).exists()
        )

    def test_access_grant_and_revoke_record_audit_events(self):
        self.client.force_login(self.user)

        grant_response = self.client.post(
            reverse("dms:document_access_manage", args=[self.document.id]),
            {"department": str(self.child_department.id)},
        )
        self.assertEqual(grant_response.status_code, 302)
        access = DocumentAccess.objects.get(
            document=self.document,
            department=self.child_department,
        )

        revoke_response = self.client.post(
            reverse("dms:document_access_revoke", args=[access.id])
        )

        self.assertEqual(revoke_response.status_code, 302)
        self.assertTrue(
            AuditEvent.objects.filter(
                document=self.document,
                event_type=AuditEvent.EventType.DOCUMENT_ACCESS_GRANTED,
                metadata__granted_department_id=self.child_department.id,
            ).exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                document=self.document,
                event_type=AuditEvent.EventType.DOCUMENT_ACCESS_REVOKED,
                metadata__revoked_department_id=self.child_department.id,
            ).exists()
        )

    @patch("dms.views.delete_document_from_index")
    def test_delete_records_audit_event_with_document_snapshot(self, delete_index_mock):
        delete_index_mock.return_value = False
        document_id = self.document.id
        self.client.force_login(self.user)

        response = self.client.post(reverse("dms:document_delete", args=[document_id]))

        self.assertEqual(response.status_code, 302)
        event = AuditEvent.objects.get(
            event_type=AuditEvent.EventType.DOCUMENT_DELETED,
            metadata__document_id=document_id,
        )
        self.assertIsNone(event.document)
        self.assertEqual(event.organization, self.department.organization)
