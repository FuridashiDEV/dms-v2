import json
import shutil
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from dms.services.search_quality import (
    EnterpriseSearchScenario,
    compare_enterprise_search_report,
    evaluate_enterprise_search_quality,
    load_enterprise_search_scenarios,
)
from dms.test_factories import make_document, make_org_context
from dms.utils import get_allowed_documents


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="dms_stage34_search_quality_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class EnterpriseSearchQualityStage34Tests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        Path(TEST_MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
        self.context = make_org_context(slug="stage-34-search", username="stage-34-user")
        self.other_context = make_org_context(slug="stage-34-other", username="stage-34-other-user")
        self._make_search_document(
            title="Pilot contract with IP Firma for tools supply",
            text="contract ip firma tools supply 3 mln tenge professional instruments",
            entities={
                "document_type": "contract",
                "counterparty": "ip firma",
                "subject": "tools supply",
                "amount": {"value": 3000000, "raw": "3 mln", "currency": "KZT"},
                "key_phrases": ["contract", "tools", "supply"],
            },
        )
        self._make_search_document(
            title="Invoice from Invision for archive search subscription",
            text="invoice invision archive search subscription platform fee",
            entities={
                "document_type": "invoice",
                "counterparty": "invision",
                "subject": "archive search subscription",
                "key_phrases": ["invoice", "invision", "subscription"],
            },
        )
        self._make_search_document(
            title="Act of completed services for workflow pilot",
            text="act completed workflow pilot services acceptance",
            entities={
                "document_type": "act",
                "subject": "workflow pilot services",
                "key_phrases": ["act", "workflow", "services"],
            },
        )
        self._make_search_document(
            title="Office rent invoice",
            text="office rent invoice unrelated payment",
            entities={"document_type": "invoice", "counterparty": "office landlord"},
        )
        other_doc = make_document(
            context=self.other_context,
            title="Pilot contract with IP Firma from other organization",
            filename="hidden.txt",
            create_version=False,
        )
        other_doc.search_text_normalized = "contract ip firma tools supply 3 mln"
        other_doc.search_entities = {"document_type": "contract", "counterparty": "ip firma"}
        other_doc.save(update_fields=["search_text_normalized", "search_entities"])

    def _make_search_document(self, *, title, text, entities):
        document = make_document(
            context=self.context,
            title=title,
            filename=f"{title[:20].replace(' ', '-').lower()}.txt",
            create_version=False,
        )
        document.description = text
        document.extracted_text = text
        document.search_text_normalized = text
        document.search_entities = entities
        document.save(update_fields=["description", "extracted_text", "search_text_normalized", "search_entities"])
        return document

    def test_golden_dataset_loads_scenarios(self):
        scenarios = load_enterprise_search_scenarios("docs/search_quality_golden.json")

        self.assertGreaterEqual(len(scenarios), 3)
        self.assertEqual(scenarios[0].id, "contract-tools-3m")
        self.assertTrue(scenarios[0].expected_labels)

    def test_enterprise_quality_metrics_include_topk_mrr_entities_and_explanations(self):
        scenarios = load_enterprise_search_scenarios("docs/search_quality_golden.json")
        queryset = get_allowed_documents(self.context.user).select_related("department", "folder", "doc_type")

        report = evaluate_enterprise_search_quality(
            user=self.context.user,
            scenarios=scenarios,
            queryset=queryset,
        )

        metrics = report["metrics"]
        self.assertEqual(metrics["total"], len(scenarios))
        self.assertEqual(metrics["top_k_accuracy"]["1"], 1.0)
        self.assertEqual(metrics["top_k_accuracy"]["3"], 1.0)
        self.assertEqual(metrics["top_k_accuracy"]["5"], 1.0)
        self.assertGreater(metrics["precision_at_k"]["3"], 0)
        self.assertGreater(metrics["recall_at_k"]["3"], 0)
        self.assertEqual(metrics["mrr"], 1.0)
        self.assertGreaterEqual(metrics["entity_match_score"], 0.75)
        self.assertGreater(metrics["explanation_coverage"], 0)
        all_titles = [row["title"] for result in report["results"] for row in result["top_results"]]
        self.assertNotIn("Pilot contract with IP Firma from other organization", all_titles)

    def test_regression_comparison_detects_metric_drop(self):
        current = {
            "metrics": {
                "top_k_accuracy": {"1": 0.5, "3": 0.75, "5": 0.75},
                "precision_at_k": {"1": 0.5, "3": 0.25, "5": 0.15},
                "recall_at_k": {"1": 0.5, "3": 0.75, "5": 0.75},
                "mrr": 0.5,
                "entity_match_score": 0.5,
                "explanation_coverage": 0.5,
            }
        }
        baseline = {
            "metrics": {
                "top_k_accuracy": {"1": 1.0, "3": 1.0, "5": 1.0},
                "precision_at_k": {"1": 1.0, "3": 0.33, "5": 0.2},
                "recall_at_k": {"1": 1.0, "3": 1.0, "5": 1.0},
                "mrr": 1.0,
                "entity_match_score": 1.0,
                "explanation_coverage": 1.0,
            }
        }

        comparison = compare_enterprise_search_report(
            current_report=current,
            baseline_report=baseline,
        )

        self.assertGreater(comparison["regression_count"], 0)
        self.assertIn("mrr", {item["metric"] for item in comparison["regressions"]})

    def test_enterprise_evaluation_command_writes_report_and_compares_baseline(self):
        output_dir = Path(TEST_MEDIA_ROOT) / "reports"
        report_path = output_dir / "current.json"
        baseline_path = output_dir / "baseline.json"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(
                {
                    "metrics": {
                        "top_k_accuracy": {"1": 0.0, "3": 0.0, "5": 0.0},
                        "precision_at_k": {"1": 0.0, "3": 0.0, "5": 0.0},
                        "recall_at_k": {"1": 0.0, "3": 0.0, "5": 0.0},
                        "mrr": 0.0,
                        "entity_match_score": 0.0,
                        "explanation_coverage": 0.0,
                    }
                }
            ),
            encoding="utf-8",
        )

        call_command(
            "evaluate_enterprise_search_quality",
            user=self.context.user.username,
            dataset="docs/search_quality_golden.json",
            baseline=str(baseline_path),
            write_report=str(report_path),
            verbosity=0,
        )

        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["user"], self.context.user.username)
        self.assertEqual(report["regression_comparison"]["regression_count"], 0)

    def test_negative_documents_are_reported_when_they_appear(self):
        scenario = EnterpriseSearchScenario(
            id="negative-check",
            query="office rent invoice",
            expected_labels=["Pilot contract with IP Firma for tools supply"],
            negative_labels=["Office rent invoice"],
        )
        queryset = get_allowed_documents(self.context.user).select_related("department", "folder", "doc_type")

        report = evaluate_enterprise_search_quality(
            user=self.context.user,
            scenarios=[scenario],
            queryset=queryset,
        )

        self.assertEqual(report["metrics"]["negative_hit_count"], 1)
