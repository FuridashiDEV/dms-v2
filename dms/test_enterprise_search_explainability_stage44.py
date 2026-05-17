import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import Department, Document, DocumentAccess, Folder
from dms.services.search_explainability import build_search_explanation, sanitize_explanation_value
from dms.services.search_intelligence import build_search_query
from dms.test_factories import make_document, make_org_context


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="dms_stage44_explainability_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class EnterpriseSearchExplainabilityServiceTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        Path(TEST_MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
        self.context = make_org_context(slug="stage-44-service")
        self.document = make_document(
            context=self.context,
            title="Contract with inVision for archive tools",
            filename="contract-invision.txt",
            create_version=False,
        )
        self.document.description = "Supply of archive tools for 3 mln tenge."
        self.document.extracted_text = "Counterparty inVision. Subject archive tools. Amount 3000000 KZT."
        self.document.search_text_normalized = "contract invision archive tools supply 3000000 kzt"
        self.document.search_entities = {
            "document_type": "contract",
            "counterparty": "invision",
            "subject": "archive tools",
            "amount": {"value": 3000000, "raw": "3 mln", "currency": "KZT"},
        }
        self.document.save(
            update_fields=["description", "extracted_text", "search_text_normalized", "search_entities"]
        )

    def test_builds_safe_structured_explanation(self):
        query = build_search_query("contract invision archive tools 3 mln")

        explanation = build_search_explanation(
            document=self.document,
            search_query=query,
            semantic_score=0.82,
            final_score=0.91,
            confidence=0.88,
            candidate_sources=["text", "alias", "vector"],
            base_reasons=["matched available document text"],
            filters={"counterparty": "inVision"},
        )

        self.assertTrue(explanation.matched_aliases)
        self.assertTrue(explanation.matched_chunks)
        self.assertTrue(explanation.matched_filters)
        self.assertGreater(explanation.semantic_score, 0)
        self.assertGreater(explanation.final_score, 0)
        self.assertTrue(any("matched" in reason for reason in explanation.human_readable_reasons))

    def test_sanitizer_redacts_sensitive_values(self):
        value = sanitize_explanation_value("payload secure_token=abc123 password: qwerty api_key=sk-test")

        self.assertNotIn("abc123", value)
        self.assertNotIn("qwerty", value)
        self.assertNotIn("sk-test", value)
        self.assertNotIn("payload", value.lower())


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class EnterpriseSearchExplainabilityViewTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        Path(TEST_MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
        self.context = make_org_context(slug="stage-44-view", username="stage-44-user")
        self.restricted_department = Department.objects.create(
            organization=self.context.organization,
            name="Restricted stage 44",
        )
        self.restricted_folder = Folder.objects.create(
            organization=self.context.organization,
            department=self.restricted_department,
            name="Restricted folder stage 44",
        )
        self.document = make_document(
            context=self.context,
            title="Semantic explainable contract",
            filename="semantic-explainable.txt",
            create_version=False,
        )
        self.document.search_text_normalized = "semantic explainable contract archive tools"
        self.document.search_entities = {
            "document_type": "contract",
            "subject": "archive tools",
        }
        self.document.save(update_fields=["search_text_normalized", "search_entities"])

    @patch("dms.views.search_documents")
    @patch("dms.views.build_embedding")
    def test_search_ui_shows_explanation_without_qdrant_payload(self, build_embedding_mock, search_documents_mock):
        build_embedding_mock.return_value = [0.1] * 384
        search_documents_mock.return_value = [
            {
                "document_id": self.document.id,
                "score": 0.84,
                "payload": {"secure_token": "do-not-render", "secret": "hidden"},
            }
        ]
        self.client.force_login(self.context.user)

        response = self.client.get(
            reverse("dms:document_list"),
            {"q": "semantic explainable archive", "search_mode": "semantic"},
        )

        self.assertEqual(response.status_code, 200)
        result = response.context["documents"][0]
        self.assertTrue(result.search_explainability.human_readable_reasons)
        content = response.content.decode()
        self.assertIn("Found because", content)
        self.assertIn("Final", content)
        self.assertNotIn("do-not-render", content)
        self.assertNotIn("secure_token", content)
        self.assertNotIn("payload", content.lower())

    @patch("dms.views.search_documents")
    @patch("dms.views.build_embedding")
    def test_explanation_does_not_disclose_inaccessible_vector_hits(self, build_embedding_mock, search_documents_mock):
        build_embedding_mock.return_value = [0.1] * 384
        accessible = Document.objects.create(
            organization=self.context.organization,
            department=self.restricted_department,
            folder=self.restricted_folder,
            title="Accessible semantic contract",
            file=SimpleUploadedFile("accessible.txt", b"payload", content_type="text/plain"),
            uploaded_by=self.context.user,
            search_text_normalized="semantic contract accessible",
        )
        hidden = Document.objects.create(
            organization=self.context.organization,
            department=self.restricted_department,
            folder=self.restricted_folder,
            title="Hidden semantic contract secret-token-999",
            file=SimpleUploadedFile("hidden.txt", b"payload", content_type="text/plain"),
            uploaded_by=self.context.user,
            search_text_normalized="semantic contract hidden secret-token-999",
        )
        DocumentAccess.objects.create(
            document=accessible,
            department=self.context.department,
            granted_by=self.context.user,
        )
        search_documents_mock.return_value = [
            {"document_id": hidden.id, "score": 0.99, "payload": {"secret": "hidden-payload"}},
            {"document_id": accessible.id, "score": 0.81, "payload": {"secret": "accessible-payload"}},
        ]
        self.client.force_login(self.context.user)

        response = self.client.get(
            reverse("dms:document_list"),
            {"q": "semantic contract", "search_mode": "semantic"},
        )

        self.assertEqual(response.status_code, 200)
        result_ids = [document.id for document in response.context["documents"]]
        self.assertIn(accessible.id, result_ids)
        self.assertNotIn(hidden.id, result_ids)
        content = response.content.decode()
        self.assertNotIn("Hidden semantic contract", content)
        self.assertNotIn("secret-token-999", content)
        self.assertNotIn("hidden-payload", content)
