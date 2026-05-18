import shutil
import tempfile
from unittest.mock import patch
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.forms import DocumentUploadForm, FolderManageForm
from dms.models import Department, Document, DocumentAccess, DocumentRelation, Folder, User
from dms.services.text_extractor import extract_text_from_file
from dms.utils import get_allowed_documents, user_can_access_document


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_test_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AccessUtilsTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.root_department = Department.objects.create(name="Root")
        self.child_department = Department.objects.create(
            name="Child",
            parent=self.root_department,
        )
        self.external_department = Department.objects.create(name="External")

        self.admin = User.objects.create_user(
            username="admin",
            password="password123",
            role=User.Role.ADMIN,
        )
        self.manager = User.objects.create_user(
            username="manager",
            password="password123",
            department=self.root_department,
        )
        self.employee = User.objects.create_user(
            username="employee",
            password="password123",
            department=self.external_department,
        )

        self.root_folder = Folder.objects.create(
            name="Reports",
            department=self.root_department,
        )

        self.root_document = Document.objects.create(
            department=self.root_department,
            folder=self.root_folder,
            title="Root document",
            file=SimpleUploadedFile("root.txt", b"root"),
            uploaded_by=self.manager,
        )
        self.child_document = Document.objects.create(
            department=self.child_department,
            title="Child document",
            file=SimpleUploadedFile("child.txt", b"child"),
            uploaded_by=self.manager,
        )
        self.external_document = Document.objects.create(
            department=self.external_department,
            title="External document",
            file=SimpleUploadedFile("external.txt", b"external"),
            uploaded_by=self.employee,
        )

    def test_admin_sees_all_documents(self):
        docs = get_allowed_documents(self.admin)

        self.assertEqual(
            set(docs.values_list("id", flat=True)),
            {
                self.root_document.id,
                self.child_document.id,
                self.external_document.id,
            },
        )

    def test_department_user_sees_own_branch_documents(self):
        docs = get_allowed_documents(self.manager)

        self.assertEqual(
            set(docs.values_list("id", flat=True)),
            {
                self.root_document.id,
                self.child_document.id,
            },
        )

    def test_explicit_access_grants_document_visibility(self):
        DocumentAccess.objects.create(
            document=self.root_document,
            department=self.external_department,
            granted_by=self.admin,
        )

        docs = get_allowed_documents(self.employee)

        self.assertEqual(
            set(docs.values_list("id", flat=True)),
            {
                self.external_document.id,
                self.root_document.id,
            },
        )
        self.assertTrue(user_can_access_document(self.employee, self.root_document))


class DocumentUploadFormTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Archive")
        self.user = User.objects.create_user(
            username="archivist",
            password="password123",
            department=self.department,
        )
        self.folder = Folder.objects.create(
            name="Reports",
            department=self.department,
        )

    def build_form(self, **overrides):
        data = {
            "department": str(self.department.id),
            "folder": str(self.folder.id),
            "new_folder": "",
            "new_subfolder": "",
            "title": "Annual report",
            "doc_type": "",
            "status": Document.Status.DRAFT,
            "doc_date": "",
            "description": "desc",
        }
        data.update(overrides)

        files = {
            "file": SimpleUploadedFile(
                "report.pdf",
                b"%PDF-1.4 test content",
                content_type="application/pdf",
            )
        }
        return DocumentUploadForm(data=data, files=files, user=self.user)

    def test_existing_folder_with_new_subfolder_is_valid(self):
        form = self.build_form(new_subfolder="2025")

        self.assertTrue(form.is_valid(), form.errors)

    def test_new_subfolder_requires_parent_folder(self):
        form = self.build_form(folder="", new_subfolder="2025")

        self.assertFalse(form.is_valid())
        self.assertIn(
            "Подпапка требует родительскую папку",
            str(form.non_field_errors()),
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

    def test_executable_file_extension_is_rejected(self):
        form = DocumentUploadForm(
            data={
                "department": str(self.department.id),
                "folder": str(self.folder.id),
                "new_folder": "",
                "new_subfolder": "",
                "title": "Unsafe file",
                "doc_type": "",
                "status": Document.Status.DRAFT,
                "doc_date": "",
                "description": "desc",
            },
            files={"file": SimpleUploadedFile("run.exe", b"MZ-binary")},
            user=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)

    def test_non_admin_form_uses_user_department_when_field_missing(self):
        form = DocumentUploadForm(
            data={
                "folder": str(self.folder.id),
                "new_folder": "",
                "new_subfolder": "",
                "title": "Annual report",
                "doc_type": "",
                "status": Document.Status.DRAFT,
                "doc_date": "",
                "description": "desc",
            },
            files={
                "file": SimpleUploadedFile(
                    "report.pdf",
                    b"%PDF-1.4 test content",
                    content_type="application/pdf",
                )
            },
            user=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["department"], self.department)


class FolderManageFormTests(TestCase):
    def setUp(self):
        self.root_department = Department.objects.create(name="Root")
        self.child_department = Department.objects.create(
            name="Child",
            parent=self.root_department,
        )
        self.user = User.objects.create_user(
            username="folder-manager",
            password="password123",
            department=self.root_department,
        )
        self.parent_folder = Folder.objects.create(
            name="Reports",
            department=self.root_department,
        )

    def test_user_can_create_subfolder_in_allowed_department(self):
        form = FolderManageForm(
            data={
                "department": str(self.root_department.id),
                "parent": str(self.parent_folder.id),
                "name": "2025",
            },
            user=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_parent_folder_must_belong_to_selected_department(self):
        form = FolderManageForm(
            data={
                "department": str(self.child_department.id),
                "parent": str(self.parent_folder.id),
                "name": "Mismatch",
            },
            user=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("parent", form.errors)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class InputValidationViewTests(TestCase):
    def setUp(self):
        self.root_department = Department.objects.create(name="Validation root")
        self.other_department = Department.objects.create(name="Validation other")
        self.user = User.objects.create_user(
            username="validator",
            password="password123",
            department=self.root_department,
        )
        self.root_folder = Folder.objects.create(
            name="Root folder",
            department=self.root_department,
        )

    def test_document_list_rejects_invalid_date_range(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dms:document_list"),
            {"date_from": "2026-12-31", "date_to": "2026-01-01"},
        )

        self.assertEqual(response.status_code, 400)

    def test_ai_parse_rejects_dangerous_file_type(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dms:ai_parse"),
            {"file": SimpleUploadedFile("payload.exe", b"MZ-binary")},
        )

        self.assertEqual(response.status_code, 400)

    def test_folders_by_department_blocks_foreign_department(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dms:folders_by_department"),
            {"department": str(self.other_department.id)},
        )

        self.assertEqual(response.status_code, 400)

    @patch("dms.views.parse_document")
    @patch("dms.views.extract_text_from_file")
    def test_ai_parse_returns_rich_metadata_from_document_text(self, extract_text_mock, parse_document_mock):
        self.client.force_login(self.user)
        extract_text_mock.return_value = (
            "Приказ ректора от 15.04.2026\n"
            "Автор: Канат Беков\n"
            "Об учебном процессе и хранении документов"
        )
        parse_document_mock.return_value = {
            "title_ru": "Приказ о порядке хранения документов",
            "summary_ru": "Документ определяет порядок хранения документов университета.",
            "doc_type": "Приказ",
            "date_index": 0,
            "document_author": "Канат Беков",
            "language": "RU",
            "retention_category": "Организационно-распорядительный документ",
            "legal_hold": False,
        }

        response = self.client.post(
            reverse("dms:ai_parse"),
            {"file": SimpleUploadedFile("order.pdf", b"%PDF-1.4 test content")},
        )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["title_ru"], "Приказ о порядке хранения документов")
        self.assertEqual(payload["summary_ru"], "Документ определяет порядок хранения документов университета.")
        self.assertEqual(payload["doc_type"], "Приказ")
        self.assertEqual(payload["language"], "RU")
        self.assertEqual(payload["document_author"], "Канат Беков")
        self.assertEqual(payload["retention_category"], "Организационно-распорядительный документ")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class FolderDeleteViewTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Archive")
        self.user = User.objects.create_user(
            username="folder-admin",
            password="password123",
            department=self.department,
        )
        self.folder = Folder.objects.create(
            name="Reports",
            department=self.department,
        )
        Document.objects.create(
            department=self.department,
            folder=self.folder,
            title="Protected",
            file=SimpleUploadedFile("protected.txt", b"doc"),
            uploaded_by=self.user,
        )

    def test_cannot_delete_folder_with_documents(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dms:folder_delete", args=[self.folder.id])
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Folder.objects.filter(id=self.folder.id).exists())


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class DocumentVersionTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Versioned")
        self.user = User.objects.create_user(
            username="version-user",
            password="password123",
            department=self.department,
        )
        self.document = Document.objects.create(
            department=self.department,
            title="Versioned document",
            file=SimpleUploadedFile("versioned.txt", b"v1"),
            uploaded_by=self.user,
        )

    def test_create_version_increments_number(self):
        first = self.document.create_version(uploaded_by=self.user)
        second = self.document.create_version(uploaded_by=self.user)

        self.assertEqual(first.number, 1)
        self.assertEqual(second.number, 2)
        self.assertEqual(self.document.current_version_number, 2)

    def test_document_version_download_requires_access(self):
        version = self.document.create_version(uploaded_by=self.user)
        outsider_department = Department.objects.create(name="Outsider")
        outsider = User.objects.create_user(
            username="outsider",
            password="password123",
            department=outsider_department,
        )
        self.client.force_login(outsider)

        response = self.client.get(
            reverse(
                "dms:document_version_download",
                args=[self.document.id, version.id],
            )
        )

        self.assertEqual(response.status_code, 403)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class DocumentDetailViewTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Docs")
        self.user = User.objects.create_user(
            username="doc-user",
            password="password123",
            department=self.department,
        )
        self.document = Document.objects.create(
            department=self.department,
            title="Detailed document",
            description="Document description",
            file=SimpleUploadedFile("detail.txt", b"detail"),
            uploaded_by=self.user,
        )
        self.document.create_version(uploaded_by=self.user)

    def test_authorized_user_can_open_document_detail(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dms:document_detail", args=[self.document.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Detailed document")

    def test_pdf_document_detail_renders_embedded_preview(self):
        pdf_document = Document.objects.create(
            department=self.department,
            title="PDF document",
            file=SimpleUploadedFile(
                "preview.pdf",
                b"%PDF-1.4 preview",
                content_type="application/pdf",
            ),
            uploaded_by=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dms:document_detail", args=[pdf_document.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="preview-frame"')

    @patch("dms.views.get_similar_documents_for_user")
    @patch("dms.views.build_document_ai_summary")
    def test_document_detail_shows_ai_summary_and_similar_documents(
        self,
        mock_build_summary,
        mock_get_similar,
    ):
        similar_document = Document.objects.create(
            department=self.department,
            title="Similar archive document",
            file=SimpleUploadedFile("similar.txt", b"similar"),
            uploaded_by=self.user,
        )
        mock_build_summary.return_value = "Краткая AI-сводка документа"
        mock_get_similar.return_value = [similar_document]
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dms:document_detail", args=[self.document.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Краткая AI-сводка документа")
        self.assertContains(response, "Similar archive document")

    def test_document_detail_shows_archive_ai_assistants(self):
        previous_revision = Document.objects.create(
            department=self.department,
            title="Detailed document 2024",
            file=SimpleUploadedFile("previous.txt", b"previous"),
            doc_date="2024-01-01",
            uploaded_by=self.user,
        )
        DocumentRelation.objects.create(
            from_document=self.document,
            to_document=previous_revision,
            relation_type=DocumentRelation.RelationType.RELATED_TO,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("dms:document_detail", args=[self.document.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Помощник по срокам хранения")
        self.assertContains(response, "Качество карточки")
        self.assertContains(response, "Проверка устаревших редакций")


class LegacyDocumentStatusWorkflowTests:
    def setUp(self):
        self.department = Department.objects.create(name="Workflow")
        self.other_department = Department.objects.create(name="Other workflow")

        self.admin = User.objects.create_user(
            username="workflow-admin",
            password="password123",
            role=User.Role.ADMIN,
        )
        self.employee = User.objects.create_user(
            username="workflow-employee",
            password="password123",
            department=self.department,
        )
        self.outsider = User.objects.create_user(
            username="workflow-outsider",
            password="password123",
            department=self.other_department,
        )

        self.document = Document.objects.create(
            department=self.department,
            title="Workflow document",
            status=Document.Status.DRAFT,
            file=SimpleUploadedFile("workflow.txt", b"workflow"),
            uploaded_by=self.employee,
        )
        self.document.create_version(uploaded_by=self.employee)

    def test_employee_can_send_document_to_review(self):
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse(
                "dms:document_change_status",
                args=[self.document.id, Document.Status.REVIEW],
            )
        )

        self.assertRedirects(
            response,
            reverse("dms:document_detail", args=[self.document.id]),
        )
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, Document.Status.REVIEW)
        self.assertEqual(self.document.current_version_number, 2)
        self.assertTrue(
            DocumentActivity.objects.filter(
                document=self.document,
                action=DocumentActivity.ACTION_SENT_TO_REVIEW,
            ).exists()
        )

    def test_employee_cannot_approve_document(self):
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse(
                "dms:document_change_status",
                args=[self.document.id, Document.Status.APPROVED],
            )
        )

        self.assertEqual(response.status_code, 403)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, Document.Status.DRAFT)

    def test_admin_can_approve_document(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse(
                "dms:document_change_status",
                args=[self.document.id, Document.Status.APPROVED],
            )
        )

        self.assertRedirects(
            response,
            reverse("dms:document_detail", args=[self.document.id]),
        )
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, Document.Status.APPROVED)
        self.assertTrue(
            DocumentActivity.objects.filter(
                document=self.document,
                action=DocumentActivity.ACTION_APPROVED,
            ).exists()
        )

    def test_outsider_cannot_change_document_status(self):
        self.client.force_login(self.outsider)

        response = self.client.post(
            reverse(
                "dms:document_change_status",
                args=[self.document.id, Document.Status.REVIEW],
            )
        )

        self.assertEqual(response.status_code, 404)


class LegacyReviewQueueViewTests:
    def setUp(self):
        self.department = Department.objects.create(name="Review department")
        self.other_department = Department.objects.create(name="Review outsiders")
        self.user = User.objects.create_user(
            username="review-user",
            password="password123",
            department=self.department,
        )
        self.outsider = User.objects.create_user(
            username="review-outsider",
            password="password123",
            department=self.other_department,
        )
        self.review_document = Document.objects.create(
            department=self.department,
            title="Needs review",
            status=Document.Status.REVIEW,
            file=SimpleUploadedFile("review.txt", b"review"),
            uploaded_by=self.user,
        )
        self.draft_document = Document.objects.create(
            department=self.department,
            title="Draft only",
            status=Document.Status.DRAFT,
            file=SimpleUploadedFile("draft.txt", b"draft"),
            uploaded_by=self.user,
        )

    def test_review_queue_shows_only_review_documents(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dms:review_queue"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Needs review")
        self.assertNotContains(response, "Draft only")

    def test_review_queue_hides_documents_from_other_departments(self):
        self.client.force_login(self.outsider)

        response = self.client.get(reverse("dms:review_queue"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Needs review")


class LegacyDocumentReviewCommentTests:
    def setUp(self):
        self.department = Department.objects.create(name="Comment department")
        self.other_department = Department.objects.create(name="Comment outsiders")
        self.user = User.objects.create_user(
            username="comment-user",
            password="password123",
            department=self.department,
        )
        self.outsider = User.objects.create_user(
            username="comment-outsider",
            password="password123",
            department=self.other_department,
        )
        self.document = Document.objects.create(
            department=self.department,
            title="Commented document",
            status=Document.Status.REVIEW,
            file=SimpleUploadedFile("comment.txt", b"comment"),
            uploaded_by=self.user,
        )

    def test_allowed_user_can_add_review_comment(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dms:document_review_comment_create", args=[self.document.id]),
            {"message": "Нужно уточнить дату приказа"},
        )

        self.assertRedirects(
            response,
            reverse("dms:document_detail", args=[self.document.id]),
        )
        self.assertTrue(
            DocumentReviewComment.objects.filter(
                document=self.document,
                user=self.user,
                message="Нужно уточнить дату приказа",
            ).exists()
        )

    def test_outsider_cannot_add_review_comment(self):
        self.client.force_login(self.outsider)

        response = self.client.post(
            reverse("dms:document_review_comment_create", args=[self.document.id]),
            {"message": "Посторонний комментарий"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            DocumentReviewComment.objects.filter(
                document=self.document,
                message="Посторонний комментарий",
            ).exists()
        )
