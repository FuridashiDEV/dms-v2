import shutil
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, TestCase, override_settings

from dms.models import ExtractedField
from dms.services.entity_extraction import extract_entities_from_text, extract_query_entities
from dms.services.search_experience import matched_entities_for_document
from dms.services.search_intelligence import (
    build_document_search_text,
    build_search_query,
    score_document_for_query,
    update_document_search_metadata,
)
from dms.test_factories import make_document, make_org_context


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="dms_stage35_entities_media_")


class AdvancedEntityExtractionTests(SimpleTestCase):
    def test_query_extracts_business_requisites_with_confidence(self):
        entities = extract_query_entities(
            "contract with IP Firma for tools amount 3 mln KZT BIN 123456789012 "
            "No ABC-42 date 12.05.2026"
        )

        self.assertEqual(entities["document_type"], "contract")
        self.assertEqual(entities["counterparty"], "ip firma")
        self.assertEqual(entities["subject"], "tools")
        self.assertEqual(entities["amount"]["value"], 3000000)
        self.assertEqual(entities["amount"]["currency"], "KZT")
        self.assertEqual(entities["bin_iin"], "123456789012")
        self.assertEqual(entities["document_number"], "abc-42")
        self.assertEqual(entities["document_date"], "2026-05-12")
        self.assertGreaterEqual(entities["entity_confidence"]["bin_iin"], 0.9)
        self.assertIn("counterparty", entities["entities_by_type"])

    def test_document_extraction_adds_table_aware_foundation(self):
        entities = extract_entities_from_text(
            "\n".join(
                [
                    "Contract No ABC-42",
                    "Counterparty: IP Firma",
                    "BIN 123456789012",
                    "Subject: supply tools amount 3 mln KZT",
                    "Item | Qty | Amount",
                    "Tools | 10 | 3000000 KZT",
                ]
            )
        )

        self.assertEqual(entities["document_number"], "abc-42")
        self.assertEqual(entities["bin_iin"], "123456789012")
        self.assertEqual(entities["amount"]["value"], 3000000)
        self.assertGreaterEqual(len(entities["table_items"]), 2)
        self.assertEqual(entities["table_items"][0]["source"], "table_text")
        self.assertIn("table_item", entities["entities_by_type"])

    def test_query_builder_keeps_stage25_compatibility_keys(self):
        query = build_search_query("contract with IP Firma for tools amount 3 mln KZT")

        self.assertEqual(query.entities["document_type"], "contract")
        self.assertEqual(query.entities["counterparty"], "ip firma")
        self.assertEqual(query.entities["subject"], "tools")
        self.assertEqual(query.entities["amount"]["value"], 3000000)
        self.assertIn("key_phrases", query.entities)
        self.assertIn("aliases", query.entities)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AdvancedEntitySearchIntegrationTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        Path(TEST_MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
        self.context = make_org_context(slug="stage-35-entities")

    def test_metadata_update_does_not_apply_entities_to_official_document_fields(self):
        document = make_document(
            context=self.context,
            title="Contract ABC-42",
            filename="contract-abc-42.txt",
            create_version=False,
        )
        document.description = "Counterparty: IP Firma. BIN 123456789012. Amount 3 mln KZT."
        document.extracted_text = "Subject: supply tools. No ABC-42. Date 12.05.2026."
        document.save(update_fields=["description", "extracted_text"])

        entities = update_document_search_metadata(document)

        self.assertEqual(entities["bin_iin"], "123456789012")
        self.assertEqual(entities["document_number"], "abc-42")
        self.assertEqual(entities["amount"]["value"], 3000000)
        document.refresh_from_db()
        self.assertEqual(document.title, "Contract ABC-42")
        self.assertEqual(ExtractedField.objects.count(), 0)

    def test_entity_matching_boosts_score_and_explanation_without_payload_leak(self):
        document = make_document(
            context=self.context,
            title="Contract ABC-42",
            filename="contract-abc-42.txt",
            create_version=False,
        )
        document.search_entities = {
            "document_type": "contract",
            "counterparty": "ip firma",
            "document_number": "abc-42",
            "bin_iin": "123456789012",
            "amount": {"value": 3000000, "raw": "3 mln kzt", "currency": "KZT"},
            "entities_by_type": {},
        }
        document.search_text_normalized = build_document_search_text(document)

        query = build_search_query("contract IP Firma ABC-42 BIN 123456789012 3 mln KZT")
        score, reasons = score_document_for_query(document, query)
        matched = matched_entities_for_document(document, query)

        self.assertGreater(score, 0.5)
        self.assertTrue(any("document_number matched" in reason for reason in reasons))
        self.assertIn("bin_iin: 123456789012", matched)
