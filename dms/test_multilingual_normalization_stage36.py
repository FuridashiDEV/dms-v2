import shutil
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, TestCase, override_settings

from dms.services.entity_extraction import extract_entities_from_text
from dms.services.search_intelligence import build_document_search_text, build_search_query, update_document_search_metadata
from dms.services.text_normalization import (
    conservative_ocr_variants,
    expand_multilingual_query,
    normalize_legal_form,
    normalize_text,
)
from dms.test_factories import make_document, make_org_context


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="dms_stage36_normalization_media_")


class MultilingualNormalizationServiceTests(SimpleTestCase):
    def test_normalize_text_preserves_raw_value_and_adds_normalized_value(self):
        result = normalize_text("InVision  Contract")

        self.assertEqual(result.raw_value, "InVision  Contract")
        self.assertEqual(result.normalized_value, "invision contract")
        self.assertIn("invision", result.tokens)
        self.assertIn("invision contract", result.variants)

    def test_legal_form_normalization_handles_ocr_lookalikes(self):
        legal_form = normalize_legal_form("T00")

        self.assertIsNotNone(legal_form)
        self.assertEqual(legal_form.normalized_value, "too")
        self.assertEqual(legal_form.raw_value, "T00")
        self.assertIn("too", legal_form.variants)

    def test_conservative_ocr_correction_adds_variants_without_replacing_raw(self):
        variants = conservative_ocr_variants("T00")

        self.assertIn("t00", variants)
        self.assertIn("too", variants)

    @override_settings(SEARCH_ALIASES={"archive pilot": ["archive-pilot", "archivepilot"]})
    def test_search_alias_expansion_uses_existing_settings_aliases(self):
        query = build_search_query("archive-pilot")

        expanded = set(query.tokens) | {value for values in query.aliases.values() for value in values}
        self.assertIn("archive pilot", expanded)
        self.assertIn("archivepilot", expanded)

    def test_multilingual_query_expansion_adds_aliases_and_variants(self):
        expansion = expand_multilingual_query("in vision contract T00")

        self.assertEqual(expansion["raw_value"], "in vision contract T00")
        self.assertEqual(expansion["normalized_value"], "in vision contract t00")
        self.assertIn("invision", expansion["expanded_terms"])
        self.assertIn("contract", expansion["expanded_terms"])
        self.assertIn("too", expansion["expanded_terms"])


class MultilingualEntityExtractionTests(SimpleTestCase):
    def test_entities_keep_raw_and_normalized_values(self):
        entities = extract_entities_from_text("Counterparty: T00 Firma. BIN 123456789012. Amount 3 mln KZT.")

        counterparty = entities["entities_by_type"]["counterparty"][0]
        self.assertIn("raw_value", counterparty)
        self.assertIn("normalized_value", counterparty)
        self.assertEqual(entities["counterparty"], "too firma")
        self.assertIn("too", entities["legal_form"])
        self.assertEqual(entities["bin_iin"], "123456789012")
        self.assertEqual(entities["amount"]["value"], 3000000)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class MultilingualSearchIntegrationTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        Path(TEST_MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
        self.context = make_org_context(slug="stage-36-normalization")

    def test_document_search_metadata_stores_normalization_without_changing_raw_fields(self):
        document = make_document(
            context=self.context,
            title="InVision agreement",
            filename="invision.txt",
            create_version=False,
        )
        document.description = "Counterparty: T00 Firma. Contract for archive pilot."
        document.save(update_fields=["description"])

        entities = update_document_search_metadata(document)
        search_text = build_document_search_text(document)

        document.refresh_from_db()
        self.assertEqual(document.title, "InVision agreement")
        self.assertEqual(entities["normalization"]["raw_value"].startswith("InVision agreement"), True)
        self.assertIn("normalized_value", entities["normalization"])
        self.assertIn("too firma", search_text)
