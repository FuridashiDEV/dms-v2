from __future__ import annotations

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from dms.services.search_experience import SearchQualityCase, evaluate_search_quality
from dms.utils import get_allowed_documents


class Command(BaseCommand):
    help = "Evaluate search quality against simple query/expected-title cases without changing documents."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Username whose permissions should be used.")
        parser.add_argument("--cases", help="JSON file with [{'query': '...', 'expected_title_contains': '...'}].")
        parser.add_argument("--limit", type=int, default=5, help="Top N results considered for each case.")

    def handle(self, *args, **options):
        user_model = get_user_model()
        user = user_model.objects.filter(username=options["user"], is_active=True).first()
        if user is None:
            raise CommandError(f"Active user not found: {options['user']}")

        queryset = (
            get_allowed_documents(user)
            .select_related("department", "folder", "doc_type")
            .order_by("-created_at")
        )
        cases = self._load_cases(options.get("cases"), queryset)
        report = evaluate_search_quality(
            user=user,
            cases=cases,
            queryset=queryset,
            limit=options["limit"],
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Search quality: "
                f"matched={report['matched']}/{report['total']} "
                f"precision@{options['limit']}={report['precision_at_limit']:.2f}"
            )
        )
        for result in report["results"]:
            status = "PASS" if result.matched else "MISS"
            self.stdout.write(f"[{status}] {result.query}")
            for title in result.top_titles:
                self.stdout.write(f"  - {title}")

    def _load_cases(self, path: str | None, queryset) -> list[SearchQualityCase]:
        if path:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            return [
                SearchQualityCase(
                    query=item["query"],
                    expected_title_contains=item.get("expected_title_contains", ""),
                )
                for item in payload
            ]

        return [
            SearchQualityCase(query=document.title, expected_title_contains=document.title)
            for document in queryset[:5]
        ]
