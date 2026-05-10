import shutil
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import Department, Document, Folder, User


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_search_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class SemanticSearchRankingTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="Archive")
        self.user = User.objects.create_user(
            username="semantic-user",
            password="password123",
            department=self.department,
        )
        self.folder = Folder.objects.create(
            name="Applications",
            department=self.department,
        )

    @patch("dms.views.search_documents")
    @patch("dms.views.build_embedding")
    def test_document_list_prefers_query_meaning_over_noisy_semantic_hit(
        self,
        build_embedding_mock,
        search_documents_mock,
    ):
        build_embedding_mock.return_value = [0.1, 0.2, 0.3]
        relevant = Document.objects.create(
            department=self.department,
            folder=self.folder,
            title="Мотивационное письмо для поступления в inVision U",
            description="Заявление кандидата с обоснованием выбора университета.",
            source_file_name="candidate_invision.docx",
            file=SimpleUploadedFile("candidate_invision.docx", b"essay"),
            uploaded_by=self.user,
        )
        irrelevant = Document.objects.create(
            department=self.department,
            folder=self.folder,
            title="Приложение к договору: техническое задание на AI-архив",
            description="Техническое задание по OCR и архивной платформе.",
            source_file_name="ocr_ai_appendix.pdf",
            file=SimpleUploadedFile("ocr_ai_appendix.pdf", b"appendix"),
            uploaded_by=self.user,
        )
        search_documents_mock.return_value = [
            {"id": irrelevant.id, "score": 0.46, "payload": {}},
            {"id": relevant.id, "score": 0.41, "payload": {}},
        ]

        self.client.force_login(self.user)
        response = self.client.get(
            reverse("dms:document_list"),
            {"q": "Заявление кандидата инвижн"},
        )

        self.assertEqual(response.status_code, 200)
        documents = list(response.context["documents"])
        self.assertGreaterEqual(len(documents), 1)
        self.assertEqual(documents[0].id, relevant.id)
        self.assertNotIn(irrelevant.id, [doc.id for doc in documents[:3]])
