import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import DocumentSearchIndexState, SearchIndexVersion
from dms.services.search_experience import (
    build_search_readiness,
    confidence_badge,
    search_mode_explanations,
)
from dms.test_factories import make_document, make_org_context


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="dms_search_ux_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AiSearchUxStage48Tests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        Path(TEST_MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
        self.context = make_org_context(slug="stage-48-search-ux", username="stage-48-user")
        self.other_context = make_org_context(slug="stage-48-other", username="stage-48-other-user")
        self.document = make_document(
            context=self.context,
            title="Contract with IP Firma for tools",
            filename="contract-tools.txt",
            create_version=False,
        )
        self.document.description = "Supply of professional tools for 3 mln tenge."
        self.document.extracted_text = "Counterparty IP Firma. Subject: tools supply. Total amount 3 mln tenge."
        self.document.search_text_normalized = "contract ip firma tools supply 3 mln tenge"
        self.document.search_entities = {
            "document_type": "contract",
            "counterparty": "ip firma",
            "subject": "tools supply",
            "amount": {"value": 3000000, "raw": "3 mln", "currency": "KZT"},
            "key_phrases": ["contract", "tools", "supply"],
        }
        self.document.save(update_fields=["description", "extracted_text", "search_text_normalized", "search_entities"])

    def test_readiness_and_confidence_helpers_are_human_readable(self):
        index_version = SearchIndexVersion.objects.create(
            embedding_model="test-model",
            embedding_dimension=3,
            qdrant_collection="test-stage-48",
        )
        DocumentSearchIndexState.objects.create(
            organization=self.context.organization,
            document=self.document,
            index_version=index_version,
            status=DocumentSearchIndexState.Status.INDEXED,
            chunks_count=3,
            qdrant_collection="test-stage-48",
        )

        readiness = build_search_readiness(self.document)
        labels = {item["label"]: item["state"] for item in readiness}

        self.assertEqual(labels["Загружен"], "ready")
        self.assertEqual(labels["Базовый поиск"], "ready")
        self.assertEqual(labels["Текст извлечён"], "ready")
        self.assertEqual(labels["Смысловой поиск готов"], "ready")
        self.assertEqual(confidence_badge(0.8)["label"], "Высокая уверенность")
        self.assertEqual(confidence_badge(0.5)["label"], "Средняя уверенность")
        self.assertEqual(confidence_badge(0.2)["label"], "Низкая уверенность")

    def test_mode_explanations_mark_active_mode(self):
        explanations = search_mode_explanations("semantic")

        self.assertEqual({item.mode for item in explanations}, {"hybrid", "exact", "semantic"})
        self.assertTrue(next(item for item in explanations if item.mode == "semantic").is_active)
        self.assertFalse(next(item for item in explanations if item.mode == "hybrid").is_active)

    @patch("dms.views.build_embedding", return_value=[])
    def test_search_page_shows_ux_layer_without_raw_payload(self, _embedding_mock):
        similar = make_document(
            context=self.context,
            title="Appendix for IP Firma tools",
            filename="appendix-tools.txt",
            create_version=False,
        )
        similar.search_text_normalized = "appendix ip firma tools"
        similar.search_entities = {
            "document_type": "appendix",
            "counterparty": "ip firma",
            "key_phrases": ["tools", "contract"],
        }
        similar.save(update_fields=["search_text_normalized", "search_entities"])
        hidden = make_document(
            context=self.other_context,
            title="Hidden IP Firma contract",
            filename="hidden-contract.txt",
            create_version=False,
        )
        hidden.search_text_normalized = "contract ip firma tools"
        hidden.search_entities = {"counterparty": "ip firma", "key_phrases": ["tools"]}
        hidden.save(update_fields=["search_text_normalized", "search_entities"])

        self.client.force_login(self.context.user)
        response = self.client.get(
            reverse("dms:document_list"),
            {"q": "contract IP Firma tools 3 mln", "search_mode": "hybrid"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Подсказки поиска")
        self.assertContains(response, "Базовый поиск")
        self.assertContains(response, "Текст извлечён")
        self.assertContains(response, "уверенность")
        self.assertNotContains(response, "Qdrant payload")
        result = next(doc for doc in response.context["documents"] if doc.id == self.document.id)
        similar_titles = [doc.title for doc in result.search_similar_documents]
        self.assertIn("Appendix for IP Firma tools", similar_titles)
        self.assertNotIn("Hidden IP Firma contract", similar_titles)
        self.assertTrue(response.context["search_suggestions"])
        self.assertTrue(response.context["search_mode_explanations"])

    @patch("dms.views.build_embedding", return_value=[])
    def test_empty_state_includes_filter_context_and_suggestions(self, _embedding_mock):
        self.client.force_login(self.context.user)

        response = self.client.get(
            reverse("dms:document_list"),
            {
                "q": "nonexistent archive phrase",
                "counterparty": "Missing vendor",
                "search_mode": "semantic",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["documents"], [])
        self.assertContains(response, "Применённые фильтры")
        self.assertContains(response, "Подсказки поиска")
        self.assertTrue(response.context["active_filter_labels"])
