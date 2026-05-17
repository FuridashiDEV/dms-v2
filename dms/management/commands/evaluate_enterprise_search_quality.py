from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from dms.services.search_quality import (
    compare_enterprise_search_report,
    evaluate_enterprise_search_quality,
    load_enterprise_search_scenarios,
)
from dms.utils import get_allowed_documents


DEFAULT_DATASET = "docs/search_quality_golden.json"


class Command(BaseCommand):
    help = "Evaluate enterprise search quality with top-k, MRR, entity, explanation, and regression metrics."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Username whose permissions should be used.")
        parser.add_argument("--dataset", default=DEFAULT_DATASET, help="Golden dataset JSON path.")
        parser.add_argument("--baseline", help="Previous report JSON path for regression comparison.")
        parser.add_argument("--write-report", help="Write current report JSON to this path.")
        parser.add_argument("--tolerance", type=float, default=0.0, help="Allowed metric drop before regression.")
        parser.add_argument("--fail-on-regression", action="store_true", help="Exit non-zero if regressions are found.")

    def handle(self, *args, **options):
        user = self._get_user(options["user"])
        dataset_path = Path(options["dataset"])
        if not dataset_path.is_absolute():
            dataset_path = Path(settings.BASE_DIR) / dataset_path
        scenarios = load_enterprise_search_scenarios(dataset_path)
        queryset = (
            get_allowed_documents(user)
            .select_related("department", "folder", "doc_type")
            .order_by("-created_at", "-id")
        )

        report = evaluate_enterprise_search_quality(
            user=user,
            scenarios=scenarios,
            queryset=queryset,
        )
        self._print_report(report)

        comparison = None
        if options.get("baseline"):
            baseline_path = Path(options["baseline"])
            if not baseline_path.is_absolute():
                baseline_path = Path(settings.BASE_DIR) / baseline_path
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            comparison = compare_enterprise_search_report(
                current_report=report,
                baseline_report=baseline,
                tolerance=options["tolerance"],
            )
            report["regression_comparison"] = comparison
            self.stdout.write(
                f"Regression comparison: {comparison['regression_count']} regression(s)"
            )
            for regression in comparison["regressions"]:
                self.stdout.write(
                    self.style.WARNING(
                        f"  {regression['metric']}: "
                        f"baseline={regression['baseline']:.4f} current={regression['current']:.4f}"
                    )
                )

        if options.get("write_report"):
            output_path = Path(options["write_report"])
            if not output_path.is_absolute():
                output_path = Path(settings.BASE_DIR) / output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            self.stdout.write(f"Report written: {output_path}")

        if comparison and comparison["regression_count"] and options["fail_on_regression"]:
            raise SystemExit(1)

    def _get_user(self, username: str):
        user_model = get_user_model()
        user = user_model.objects.filter(username=username, is_active=True).first()
        if user is None:
            raise CommandError(f"Active user not found: {username}")
        return user

    def _print_report(self, report):
        metrics = report["metrics"]
        top_accuracy = metrics["top_k_accuracy"]
        precision = metrics["precision_at_k"]
        recall = metrics["recall_at_k"]
        self.stdout.write(
            self.style.SUCCESS(
                "Enterprise search quality: "
                f"cases={metrics['total']} "
                f"top1={top_accuracy.get('1', 0):.2f} "
                f"top3={top_accuracy.get('3', 0):.2f} "
                f"top5={top_accuracy.get('5', 0):.2f} "
                f"p@3={precision.get('3', 0):.2f} "
                f"r@3={recall.get('3', 0):.2f} "
                f"mrr={metrics['mrr']:.2f} "
                f"entity={metrics['entity_match_score']:.2f} "
                f"explain={metrics['explanation_coverage']:.2f}"
            )
        )
        for result in report["results"]:
            status = "PASS" if result["top_k_accuracy"].get("5") else "MISS"
            self.stdout.write(f"[{status}] {result['scenario_id']}: {result['query']}")
            for row in result["top_results"][:5]:
                self.stdout.write(
                    f"  {row['rank']}. {row['title']} "
                    f"score={row['score']:.4f}"
                )
