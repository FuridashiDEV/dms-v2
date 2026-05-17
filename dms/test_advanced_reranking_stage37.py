import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import DocumentRelation
from dms.services.reranking import (
    SOURCE_ENTITY,
    SOURCE_TEXT,
    SOURCE_VECTOR,
    calculate_confidence,
    calculate_final_score,
    fuse_candidates,
    rank_documents_for_search,
)
from dms.services.search_intelligence import build_search_query, build_document_search_text
from dms.test_factories import make_document, make_org_context


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="dms_stage37_reranking_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AdvancedRerankingServiceTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        Path(TEST_MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
        self.context = make_org_context(slug="stage-37-reranking")

    def test_fusion_combines_candidate_sources_and_scores(self):
        fused = fuse_candidates(
            text_ids=[1, 2],
            entity_ids=[1],
            vector_scores={2: 0.91},
        )

        self.assertEqual(set(fused.keys()), {1, 2})
        self.assertIn(SOURCE_TEXT, fused[1].sources)
        self.assertIn(SOURCE_ENTITY, fused[1].sources)
        self.assertIn(SOURCE_VECTOR, fused[2].sources)
        self.assertGreater(fused[2].fusion_score, 0)

    def test_final_score_and_confidence_are_bounded(self):
        final_score = calculate_final_score(base_score=1.2, fusion_score=0.8, reranker_score=0.5)
        confidence = calculate_confidence(final_score=final_score, source_count=3, reason_count=4)

        self.assertGreater(final_score, 0.8)
        self.assertLessEqual(final_score, 1.25)
        self.assertGreater(confidence, 0.7)
        self.assertLessEqual(confidence, 1.0)

    def test_ranker_keeps_model_reranker_optional_and_explains_score(self):
        exact = make_document(
            context=self.context,
            title="Contract with IP Firma for tools supply",
            filename="exact.txt",
            create_version=False,
        )
        exact.search_entities = {
            "document_type": "contract",
            "counterparty": "ip firma",
            "subject": "tools supply",
            "amount": {"value": 3000000, "raw": "3 mln kzt", "currency": "KZT"},
        }
        exact.search_text_normalized = build_document_search_text(exact)
        exact.save(update_fields=["search_entities", "search_text_normalized"])

        semantic_only = make_document(
            context=self.context,
            title="Generic office invoice",
            filename="semantic.txt",
            create_version=False,
        )
        semantic_only.search_text_normalized = "generic office invoice"
        semantic_only.save(update_fields=["search_text_normalized"])

        query = build_search_query("contract IP Firma tools 3 mln")
        fused = fuse_candidates(
            text_ids=[exact.id],
            entity_ids=[exact.id],
            vector_scores={semantic_only.id: 0.95},
        )

        ranked = rank_documents_for_search(
            documents=[semantic_only, exact],
            search_query=query,
            fused_candidates=fused,
            reranker=None,
        )

        self.assertEqual(ranked[0].document.id, exact.id)
        self.assertGreater(ranked[0].confidence, 0)
        self.assertTrue(any("candidate sources" in reason for reason in ranked[0].reasons))
        self.assertTrue(any("final score" in reason for reason in ranked[0].reasons))


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AdvancedRerankingViewTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        Path(TEST_MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
        self.context = make_org_context(slug="stage-37-view", username="stage-37-user")
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

    @patch("dms.views.build_embedding", return_value=[])
    def test_search_works_without_qdrant_or_model_reranker(self, _embedding_mock):
        self.client.force_login(self.context.user)

        response = self.client.get(
            reverse("dms:document_list"),
            {"q": "tools supply", "search_mode": "semantic"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["search_mode"], "semantic_fallback")
        result = next(doc for doc in response.context["documents"] if doc.id == self.document.id)
        self.assertGreater(result.search_confidence, 0)
        self.assertGreater(result.search_final_score, 0)
        self.assertIn("text", result.search_candidate_sources)
        self.assertTrue(any("final score" in reason for reason in result.search_explanation))

    @patch("dms.views.build_embedding", return_value=[])
    def test_related_candidates_are_permission_checked(self, _embedding_mock):
        related = make_document(
            context=self.context,
            title="Appendix for tools contract",
            filename="appendix.txt",
            create_version=False,
        )
        related.search_text_normalized = "appendix tools contract"
        related.save(update_fields=["search_text_normalized"])
        DocumentRelation.objects.create(
            from_document=self.document,
            to_document=related,
            relation_type=DocumentRelation.RelationType.APPENDIX_TO,
        )
        self.client.force_login(self.context.user)

        response = self.client.get(reverse("dms:document_list"), {"q": "tools"})

        self.assertEqual(response.status_code, 200)
        result_ids = [doc.id for doc in response.context["documents"]]
        self.assertIn(self.document.id, result_ids)
        self.assertIn(related.id, result_ids)
