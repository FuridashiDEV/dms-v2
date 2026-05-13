import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import Department, DocumentRelation
from dms.test_factories import make_document, make_org_context


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="dms_search_experience_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class SearchExperienceStage26Tests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        Path(TEST_MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
        self.context = make_org_context(slug="stage-26-search", username="stage-26-user")
        self.other_context = make_org_context(slug="stage-26-other", username="stage-26-other-user")
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
        self.document.save(
            update_fields=["description", "extracted_text", "search_text_normalized", "search_entities"]
        )

    @patch("dms.views.search_documents")
    @patch("dms.views.build_embedding")
    def test_exact_mode_uses_text_without_semantic_call(self, build_embedding_mock, search_documents_mock):
        self.client.force_login(self.context.user)

        response = self.client.get(
            reverse("dms:document_list"),
            {"q": "IP Firma", "search_mode": "exact"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["search_mode"], "exact")
        self.assertIn(self.document.id, [doc.id for doc in response.context["documents"]])
        build_embedding_mock.assert_not_called()
        search_documents_mock.assert_not_called()

    @patch("dms.views.build_embedding")
    def test_semantic_mode_degrades_to_safe_text_results(self, build_embedding_mock):
        build_embedding_mock.return_value = []
        self.client.force_login(self.context.user)

        response = self.client.get(
            reverse("dms:document_list"),
            {"q": "tools supply", "search_mode": "semantic"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["search_degraded"])
        self.assertEqual(response.context["search_mode"], "semantic_fallback")
        self.assertIn(self.document.id, [doc.id for doc in response.context["documents"]])

    @patch("dms.views.build_embedding", return_value=[])
    def test_counterparty_and_amount_filters_are_applied(self, _embedding_mock):
        other = make_document(
            context=self.context,
            title="Small office invoice",
            filename="small.txt",
            create_version=False,
        )
        other.search_text_normalized = "invoice other vendor office"
        other.search_entities = {
            "document_type": "invoice",
            "counterparty": "other vendor",
            "amount": {"value": 100000, "raw": "100000"},
        }
        other.save(update_fields=["search_text_normalized", "search_entities"])
        self.client.force_login(self.context.user)

        response = self.client.get(
            reverse("dms:document_list"),
            {
                "q": "contract",
                "counterparty": "IP Firma",
                "amount_min": "2000000",
                "amount_max": "4000000",
            },
        )

        self.assertEqual(response.status_code, 200)
        result_ids = [doc.id for doc in response.context["documents"]]
        self.assertIn(self.document.id, result_ids)
        self.assertNotIn(other.id, result_ids)

    @patch("dms.views.build_embedding", return_value=[])
    def test_result_has_snippet_explanation_and_only_accessible_related_documents(self, _embedding_mock):
        related = make_document(
            context=self.context,
            title="Appendix for tools contract",
            filename="appendix.txt",
            create_version=False,
        )
        private_department = Department.objects.create(
            organization=self.context.organization,
            name="Private stage 26",
        )
        hidden = make_document(
            context=self.context,
            title="Hidden related appendix",
            filename="hidden.txt",
            create_version=False,
        )
        hidden.department = private_department
        hidden.save(update_fields=["department"])
        DocumentRelation.objects.create(
            from_document=self.document,
            to_document=related,
            relation_type=DocumentRelation.RelationType.APPENDIX_TO,
        )
        DocumentRelation.objects.create(
            from_document=self.document,
            to_document=hidden,
            relation_type=DocumentRelation.RelationType.RELATED_TO,
        )
        self.client.force_login(self.context.user)

        response = self.client.get(reverse("dms:document_list"), {"q": "tools"})

        self.assertEqual(response.status_code, 200)
        result = next(doc for doc in response.context["documents"] if doc.id == self.document.id)
        self.assertIn("tools", result.search_snippet.lower())
        self.assertTrue(result.search_explanation)
        related_titles = [item["document"].title for item in result.search_related_documents]
        self.assertIn("Appendix for tools contract", related_titles)
        self.assertNotIn("Hidden related appendix", related_titles)

    @patch("dms.management.commands.evaluate_search_quality.evaluate_search_quality")
    def test_quality_evaluation_command_runs_with_user_permissions(self, evaluate_mock):
        evaluate_mock.return_value = {
            "user": self.context.user.username,
            "total": 1,
            "matched": 1,
            "precision_at_limit": 1.0,
            "results": [],
        }

        call_command("evaluate_search_quality", user=self.context.user.username, limit=3, verbosity=0)

        evaluate_mock.assert_called_once()
