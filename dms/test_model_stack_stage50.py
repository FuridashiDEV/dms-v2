from __future__ import annotations

import io
import json

from django.core.management import call_command
from django.test import TestCase, override_settings

from dms.models import SearchIndexVersion
from dms.services.index_versions import get_active_search_index_version
from dms.services.model_stack import (
    BGE_M3_MODEL,
    BGE_RERANKER_V2_M3_MODEL,
    MULTILINGUAL_E5_LARGE_MODEL,
    NOOP_RERANKER_MODEL,
    collection_name_for_model,
    get_embedding_adapter,
    get_reranker_adapter,
    registry_snapshot,
    stable_synthetic_embedding,
    validate_embedding_vector,
)


class ModelStackStage50Tests(TestCase):
    def test_registry_contains_required_embedding_and_reranker_candidates(self):
        snapshot = registry_snapshot()

        self.assertIn(BGE_M3_MODEL, snapshot["embeddings"])
        self.assertIn(MULTILINGUAL_E5_LARGE_MODEL, snapshot["embeddings"])
        self.assertIn("all-MiniLM-L6-v2", snapshot["embeddings"])
        self.assertEqual(snapshot["embeddings"][BGE_M3_MODEL]["dimension"], 1024)
        self.assertEqual(snapshot["embeddings"][MULTILINGUAL_E5_LARGE_MODEL]["dimension"], 1024)
        self.assertIn(BGE_RERANKER_V2_M3_MODEL, snapshot["rerankers"])
        self.assertIn(NOOP_RERANKER_MODEL, snapshot["rerankers"])

    def test_e5_adapter_applies_query_and_passage_prefixes(self):
        adapter = get_embedding_adapter(MULTILINGUAL_E5_LARGE_MODEL)

        self.assertEqual(adapter.prepare_query("договор"), "query: договор")
        self.assertEqual(adapter.prepare_passage("договор"), "passage: договор")
        self.assertEqual(adapter.prepare_query("query: договор"), "query: договор")

    def test_vector_dimension_validation_rejects_wrong_dimensions(self):
        valid = stable_synthetic_embedding("contract", dimension=1024)

        self.assertTrue(validate_embedding_vector(valid, model_name=BGE_M3_MODEL).valid)
        invalid = validate_embedding_vector([0.1, 0.2], model_name=BGE_M3_MODEL)
        self.assertFalse(invalid.valid)
        self.assertEqual(invalid.reason, "dimension_mismatch")

    @override_settings(
        SEARCH_EMBEDDING_MODEL=BGE_M3_MODEL,
        SEARCH_EMBEDDING_VECTOR_SIZE=1024,
        QDRANT_COLLECTION="documents_baai_bge_m3",
    )
    def test_search_index_version_uses_model_dimension_and_collection(self):
        version = get_active_search_index_version()

        self.assertIsInstance(version, SearchIndexVersion)
        self.assertEqual(version.embedding_model, BGE_M3_MODEL)
        self.assertEqual(version.embedding_dimension, 1024)
        self.assertEqual(version.qdrant_collection, "documents_baai_bge_m3")

    def test_noop_reranker_preserves_safe_fallback(self):
        reranker = get_reranker_adapter(NOOP_RERANKER_MODEL)
        results = reranker.rerank(query="договор", passages=["one", "two"], top_k=2)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].score, 0.0)
        self.assertIn("noop", results[0].reason)

    def test_collection_name_is_model_specific(self):
        self.assertEqual(collection_name_for_model(BGE_M3_MODEL), "documents_baai_bge_m3")
        self.assertEqual(
            collection_name_for_model(MULTILINGUAL_E5_LARGE_MODEL),
            "documents_intfloat_multilingual_e5_large",
        )

    def test_benchmark_model_stack_outputs_required_metrics_without_loading_models(self):
        stdout = io.StringIO()

        call_command("benchmark_model_stack", "--dataset", "synthetic", "--limit", "3", "--format", "json", stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["dataset"], "synthetic")
        self.assertFalse(payload["load_models"])
        report = payload["reports"][0]
        metrics = report["metrics"]
        for key in (
            "top_1_accuracy",
            "top_3_accuracy",
            "top_5_accuracy",
            "mrr",
            "precision_at_5",
            "recall_at_10",
            "average_latency_ms",
            "p95_latency_ms",
            "embedding_time_per_document_ms",
            "reranking_latency_ms",
            "qdrant_insert_time_ms",
            "fallback_count",
        ):
            self.assertIn(key, metrics)
        self.assertEqual(report["vector_dimension"], 1024)
        self.assertTrue(report["search_index_version_compatible"])
