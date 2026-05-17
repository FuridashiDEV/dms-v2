from __future__ import annotations

from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from dms.models import DocumentSearchIndexState, SearchIndexVersion
from dms.services.document_indexing import index_document
from dms.services.index_versions import get_active_search_index_version, is_document_index_stale
from dms.services.vector_store import make_point_id
from dms.test_factories import make_document, make_org_context


@override_settings(
    SEARCH_EMBEDDING_MODEL="all-MiniLM-L6-v2",
    SEARCH_EMBEDDING_VECTOR_SIZE=384,
    SEARCH_CHUNKING_VERSION="stage40-chunking-v1",
    SEARCH_NORMALIZATION_VERSION="stage40-normalization-v1",
    QDRANT_COLLECTION="documents_stage40_all_minilm",
)
class IncrementalIndexingStage40Tests(TestCase):
    def setUp(self):
        self.context = make_org_context(slug="stage-40")
        self.document = make_document(context=self.context, title="Stage 40 contract")
        self.document.description = "Indexed incrementally"
        self.document.extracted_text = "Counterparty IP Firma. Amount 3 mln tenge."
        self.document.save(update_fields=["description", "extracted_text"])

    def test_active_index_version_uses_model_dimension_collection_and_versions(self):
        version = get_active_search_index_version()

        self.assertEqual(version.embedding_model, "all-MiniLM-L6-v2")
        self.assertEqual(version.embedding_dimension, 384)
        self.assertEqual(version.chunking_version, "stage40-chunking-v1")
        self.assertEqual(version.normalization_version, "stage40-normalization-v1")
        self.assertEqual(version.qdrant_collection, "documents_stage40_all_minilm")
        self.assertTrue(version.is_active)

    def test_stable_point_id_includes_document_version_chunk_and_index_version(self):
        version = get_active_search_index_version()
        document_version = self.document.versions.order_by("-number").first()

        first = make_point_id(
            doc_id=self.document.id,
            document_version_id=document_version.id,
            chunk_key="content-1",
            index_version_id=version.id,
            collection_name=version.qdrant_collection,
        )
        second = make_point_id(
            doc_id=self.document.id,
            document_version_id=document_version.id,
            chunk_key="content-1",
            index_version_id=version.id,
            collection_name=version.qdrant_collection,
        )
        changed_chunk = make_point_id(
            doc_id=self.document.id,
            document_version_id=document_version.id,
            chunk_key="content-2",
            index_version_id=version.id,
            collection_name=version.qdrant_collection,
        )

        self.assertEqual(first, second)
        self.assertNotEqual(first, changed_chunk)

    @patch("dms.services.vector_store.delete_points", return_value=True)
    @patch("dms.services.document_indexing.upsert_document_chunks", return_value=True)
    @patch("dms.services.document_indexing.build_embeddings_batch")
    def test_index_document_records_state_and_does_safe_point_cleanup(
        self,
        build_embeddings_batch_mock,
        _upsert_mock,
        delete_points_mock,
    ):
        build_embeddings_batch_mock.side_effect = lambda texts: [[0.1] * 384 for _text in texts]
        version = get_active_search_index_version()
        previous = DocumentSearchIndexState.objects.create(
            organization=self.context.organization,
            document=self.document,
            document_version=self.document.versions.order_by("-number").first(),
            index_version=version,
            status=DocumentSearchIndexState.Status.INDEXED,
            qdrant_collection=version.qdrant_collection,
            content_hash="old",
            point_ids=["old-point-id"],
        )

        self.assertTrue(index_document(self.document))

        previous.refresh_from_db()
        self.assertEqual(previous.status, DocumentSearchIndexState.Status.INDEXED)
        self.assertGreater(previous.chunks_count, 0)
        self.assertNotEqual(previous.content_hash, "old")
        self.assertTrue(previous.point_ids)
        delete_points_mock.assert_called_once_with(point_ids=["old-point-id"])

    @patch("dms.services.vector_store.delete_points", return_value=True)
    @patch("dms.services.document_indexing.upsert_document_chunks", return_value=True)
    @patch("dms.services.document_indexing.build_embeddings_batch")
    def test_stale_detection_changes_after_document_content_changes(
        self,
        build_embeddings_batch_mock,
        _upsert_mock,
        _delete_points_mock,
    ):
        build_embeddings_batch_mock.side_effect = lambda texts: [[0.1] * 384 for _text in texts]

        self.assertTrue(index_document(self.document))
        self.document.refresh_from_db()
        self.assertFalse(is_document_index_stale(self.document))

        self.document.extracted_text = "Counterparty changed. Amount 5 mln tenge."
        self.document.save(update_fields=["extracted_text"])
        self.document.refresh_from_db()

        self.assertTrue(is_document_index_stale(self.document))

    @patch("dms.management.commands.reindex_search.index_document")
    def test_reindex_only_stale_skips_current_documents(self, index_document_mock):
        index_document_mock.return_value = True
        version = get_active_search_index_version()
        DocumentSearchIndexState.objects.create(
            organization=self.context.organization,
            document=self.document,
            document_version=self.document.versions.order_by("-number").first(),
            index_version=version,
            status=DocumentSearchIndexState.Status.INDEXED,
            qdrant_collection=version.qdrant_collection,
            content_hash="not-current",
            point_ids=["point-1"],
        )

        call_command("reindex_search", only_stale=True, verbosity=0)

        index_document_mock.assert_called_once()

    def test_same_collection_cannot_mix_active_embedding_dimensions(self):
        SearchIndexVersion.objects.create(
            embedding_model="different-model",
            embedding_dimension=768,
            chunking_version="stage40-chunking-v1",
            normalization_version="stage40-normalization-v1",
            qdrant_collection="documents_stage40_all_minilm",
            is_active=True,
        )

        with self.assertRaises(ValueError):
            get_active_search_index_version()
