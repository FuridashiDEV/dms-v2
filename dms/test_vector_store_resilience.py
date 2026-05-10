from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from dms.services import vector_store


class VectorStoreResilienceTests(SimpleTestCase):
    def setUp(self):
        vector_store._collection_ready = False

    def tearDown(self):
        vector_store._collection_ready = False

    @patch("dms.services.vector_store.get_client")
    def test_upsert_returns_false_when_qdrant_is_unavailable(self, get_client_mock):
        client = get_client_mock.return_value
        client.get_collections.side_effect = RuntimeError("qdrant unavailable")
        client.upsert.side_effect = AssertionError("upsert should not run")

        result = vector_store.upsert_document(
            doc_id=1,
            vector=[0.0] * vector_store.VECTOR_SIZE,
            payload={"department_id": 1},
        )

        self.assertFalse(result)
        client.upsert.assert_not_called()

    @patch("dms.services.vector_store.get_client")
    def test_search_accepts_legacy_vector_arguments(self, get_client_mock):
        client = get_client_mock.return_value
        client.get_collections.return_value = SimpleNamespace(
            collections=[SimpleNamespace(name=vector_store.COLLECTION_NAME)]
        )
        client.query_points.return_value = SimpleNamespace(points=[])

        result = vector_store.search_documents(
            query_vector=[0.0] * vector_store.VECTOR_SIZE,
            department_ids=[1],
            limit=5,
        )

        self.assertEqual(result, [])
        client.query_points.assert_called_once()
