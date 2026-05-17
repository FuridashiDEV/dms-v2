import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from dms.models import Department, Document, DocumentAccess, Folder, User
from dms.services.document_indexing import build_document_index_chunks, index_document
from dms.services.embedding import get_embedding_model_name
from dms.services.search_intelligence import build_search_query, extract_entities_from_text
from dms.test_factories import make_document, make_org_context


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="dms_search_intelligence_media_")


class SearchEntityExtractionTests(SimpleTestCase):
    def test_business_query_is_normalized_into_entities(self):
        query = build_search_query("договор с ИП Фирма на поставку инструментов на 3 млн")

        self.assertEqual(query.entities["document_type"], "contract")
        self.assertEqual(query.entities["counterparty"], "ип фирма")
        self.assertEqual(query.entities["subject"], "поставку инструментов")
        self.assertEqual(query.entities["amount"]["value"], 3000000)
        self.assertIn("индивидуальный предприниматель", query.aliases["ип"])

    def test_aliases_connect_latin_and_russian_brand_variants(self):
        query = build_search_query("контракт invision")

        self.assertIn("invision", query.aliases)
        self.assertIn("инвижн", query.aliases["invision"])
        self.assertIn("инвижен", query.aliases["invision"])

    def test_document_entities_are_extracted_from_document_text(self):
        entities = extract_entities_from_text(
            "Договор. Контрагент: ИП Фирма. Предмет: поставка инструментов на 3 млн тенге.",
            doc_type_name="Договор",
        )

        self.assertEqual(entities["document_type"], "contract")
        self.assertEqual(entities["counterparty"], "ип фирма")
        self.assertEqual(entities["amount"]["value"], 3000000)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class SearchIndexingTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        Path(TEST_MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
        self.context = make_org_context(slug="stage-25-index")

    @patch("dms.services.vector_store.delete_points", return_value=True)
    @patch("dms.services.document_indexing.upsert_document_chunks")
    @patch("dms.services.document_indexing.build_embeddings_batch")
    def test_index_document_builds_multi_level_chunks_and_payload(
        self,
        build_embeddings_batch_mock,
        upsert_document_chunks_mock,
        _delete_points_mock,
    ):
        document = make_document(
            context=self.context,
            title="Договор с ИП Фирма",
            filename="contract.txt",
            content=b"contract",
            create_version=False,
        )
        document.description = "Поставка инструментов на 3 млн тенге"
        document.extracted_text = "Контрагент: ИП Фирма. Предмет поставки: инструменты."
        document.save(update_fields=["description", "extracted_text"])
        upsert_document_chunks_mock.return_value = True
        build_embeddings_batch_mock.side_effect = lambda texts: [[0.1] * 384 for _ in texts]

        self.assertTrue(index_document(document))

        document.refresh_from_db()
        self.assertEqual(document.search_embedding_model, get_embedding_model_name())
        self.assertEqual(document.search_entities["amount"]["value"], 3000000)
        chunks = build_document_index_chunks(document)
        self.assertGreaterEqual(len(chunks), 3)
        payload_chunks = upsert_document_chunks_mock.call_args.kwargs["chunks"]
        self.assertGreaterEqual(len(payload_chunks), 3)
        first_payload = payload_chunks[0]["payload"]
        self.assertEqual(first_payload["document_id"], document.id)
        self.assertEqual(first_payload["organization_id"], self.context.organization.id)
        self.assertEqual(first_payload["embedding_model"], get_embedding_model_name())
        self.assertIn("search_index_version_id", first_payload)

    @patch("dms.management.commands.reindex_search.index_document")
    def test_reindex_command_can_reindex_one_document(self, index_document_mock):
        document = make_document(context=self.context, create_version=False)
        index_document_mock.return_value = True

        call_command("reindex_search", document_id=document.id, verbosity=0)

        index_document_mock.assert_called_once()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class HybridSearchSecurityTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        Path(TEST_MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
        self.context = make_org_context(slug="stage-25-search", username="stage-25-user")
        self.other_context = make_org_context(slug="stage-25-other", username="stage-25-other-user")
        self.other_department = Department.objects.create(
            organization=self.context.organization,
            name="Restricted",
        )
        self.other_folder = Folder.objects.create(
            organization=self.context.organization,
            department=self.other_department,
            name="Restricted folder",
        )

    @patch("dms.views.build_embedding")
    def test_alias_search_falls_back_to_text_and_keeps_organization_isolation(self, build_embedding_mock):
        build_embedding_mock.return_value = []
        visible = make_document(
            context=self.context,
            title="Contract with inVision for archive pilot",
            filename="visible.txt",
            create_version=False,
        )
        make_document(
            context=self.other_context,
            title="Contract with inVision from another organization",
            filename="hidden.txt",
            create_version=False,
        )

        self.client.force_login(self.context.user)
        response = self.client.get(reverse("dms:document_list"), {"q": "инвижн"})

        self.assertEqual(response.status_code, 200)
        result_ids = [document.id for document in response.context["documents"]]
        self.assertIn(visible.id, result_ids)
        self.assertEqual(len(result_ids), 1)

    @patch("dms.views.search_documents")
    @patch("dms.views.build_embedding")
    def test_vector_search_uses_organization_filter_and_final_document_access(
        self,
        build_embedding_mock,
        search_documents_mock,
    ):
        build_embedding_mock.return_value = [0.1] * 384
        accessible = Document.objects.create(
            organization=self.context.organization,
            department=self.other_department,
            folder=self.other_folder,
            title="Semantic-only accessible contract",
            file=SimpleUploadedFile("accessible.txt", b"payload", content_type="text/plain"),
            uploaded_by=self.context.user,
        )
        hidden = Document.objects.create(
            organization=self.context.organization,
            department=self.other_department,
            folder=self.other_folder,
            title="Semantic-only hidden contract",
            file=SimpleUploadedFile("hidden.txt", b"payload", content_type="text/plain"),
            uploaded_by=self.context.user,
        )
        DocumentAccess.objects.create(
            document=accessible,
            department=self.context.department,
            granted_by=self.context.user,
        )
        search_documents_mock.return_value = [
            {"document_id": accessible.id, "score": 0.72, "payload": {}},
            {"document_id": hidden.id, "score": 0.75, "payload": {}},
        ]

        self.client.force_login(self.context.user)
        response = self.client.get(reverse("dms:document_list"), {"q": "semantic query"})

        self.assertEqual(response.status_code, 200)
        call_filters = search_documents_mock.call_args.kwargs["filters"]
        self.assertEqual(call_filters["organization_id"], [self.context.organization.id])
        result_ids = [document.id for document in response.context["documents"]]
        self.assertIn(accessible.id, result_ids)
        self.assertNotIn(hidden.id, result_ids)
