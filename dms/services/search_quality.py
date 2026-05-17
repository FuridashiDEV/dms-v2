from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from django.db.models import QuerySet

from dms.models import Document
from dms.services.search_experience import build_search_snippet
from dms.services.search_intelligence import build_search_query, normalize_search_text, score_document_for_query


DEFAULT_TOP_K = (1, 3, 5)


@dataclass(frozen=True)
class EnterpriseSearchScenario:
    id: str
    query: str
    expected_labels: list[str]
    expected_type: str = ""
    expected_entities: dict[str, Any] = field(default_factory=dict)
    negative_labels: list[str] = field(default_factory=list)
    language: str = "ru"
    mode: str = "hybrid"
    notes: str = ""


@dataclass(frozen=True)
class EnterpriseSearchResult:
    scenario_id: str
    query: str
    expected_labels: list[str]
    top_results: list[dict[str, Any]]
    first_relevant_rank: int | None
    top_k_accuracy: dict[str, bool]
    precision_at_k: dict[str, float]
    recall_at_k: dict[str, float]
    mrr: float
    entity_match_score: float
    explanation_coverage: float
    negative_hit_count: int

    @property
    def passed_top_5(self) -> bool:
        return self.top_k_accuracy.get("5", False)


def load_enterprise_search_scenarios(path: str | Path) -> list[EnterpriseSearchScenario]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Search quality dataset must be a JSON list.")
    scenarios = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Scenario #{index} must be an object.")
        query = str(item.get("query", "")).strip()
        expected_labels = [str(label).strip() for label in item.get("expected_labels", []) if str(label).strip()]
        if not query or not expected_labels:
            raise ValueError(f"Scenario #{index} must include query and expected_labels.")
        scenarios.append(
            EnterpriseSearchScenario(
                id=str(item.get("id") or f"scenario-{index}"),
                query=query,
                expected_labels=expected_labels,
                expected_type=str(item.get("expected_type", "")),
                expected_entities=item.get("expected_entities") or {},
                negative_labels=[
                    str(label).strip()
                    for label in item.get("negative_labels", [])
                    if str(label).strip()
                ],
                language=str(item.get("language") or "ru"),
                mode=str(item.get("mode") or "hybrid"),
                notes=str(item.get("notes") or ""),
            )
        )
    return scenarios


def evaluate_enterprise_search_quality(
    *,
    user,
    scenarios: list[EnterpriseSearchScenario],
    queryset: QuerySet,
    top_k_values: tuple[int, ...] = DEFAULT_TOP_K,
) -> dict[str, Any]:
    results = [
        evaluate_enterprise_search_scenario(
            user=user,
            scenario=scenario,
            queryset=queryset,
            top_k_values=top_k_values,
        )
        for scenario in scenarios
    ]
    return build_enterprise_search_report(user=user, results=results, top_k_values=top_k_values)


def evaluate_enterprise_search_scenario(
    *,
    user,
    scenario: EnterpriseSearchScenario,
    queryset: QuerySet,
    top_k_values: tuple[int, ...] = DEFAULT_TOP_K,
) -> EnterpriseSearchResult:
    del user
    max_k = max(top_k_values) if top_k_values else 5
    search_query = build_search_query(scenario.query)
    scored = []
    for document in queryset:
        score, reasons = score_document_for_query(document, search_query, semantic_score=0.0)
        if score <= 0:
            continue
        scored.append((score, document, reasons))

    scored.sort(key=lambda item: (item[0], item[1].created_at, item[1].id), reverse=True)
    ranked = scored[:max_k]
    top_results = [
        _serialize_ranked_document(rank=rank, document=document, score=score, reasons=reasons, search_query=search_query)
        for rank, (score, document, reasons) in enumerate(ranked, start=1)
    ]

    relevant_ranks = [
        row["rank"]
        for row in top_results
        if _document_matches_expected_labels(row, scenario.expected_labels)
    ]
    first_relevant_rank = min(relevant_ranks) if relevant_ranks else None
    negative_hit_count = sum(
        1
        for row in top_results
        if _document_matches_expected_labels(row, scenario.negative_labels)
    )

    top_k_accuracy = {}
    precision_at_k = {}
    recall_at_k = {}
    for k in top_k_values:
        rows = top_results[:k]
        relevant_count = sum(1 for row in rows if _document_matches_expected_labels(row, scenario.expected_labels))
        top_k_accuracy[str(k)] = relevant_count > 0
        precision_at_k[str(k)] = round(relevant_count / k, 4) if k else 0.0
        recall_at_k[str(k)] = round(relevant_count / max(len(scenario.expected_labels), 1), 4)

    relevant_rows = [
        row for row in top_results if _document_matches_expected_labels(row, scenario.expected_labels)
    ]
    entity_match_score = _entity_match_score(relevant_rows[:1], scenario.expected_entities)
    explanation_coverage = _explanation_coverage(top_results[:max_k])
    mrr = round(1 / first_relevant_rank, 4) if first_relevant_rank else 0.0

    return EnterpriseSearchResult(
        scenario_id=scenario.id,
        query=scenario.query,
        expected_labels=scenario.expected_labels,
        top_results=top_results,
        first_relevant_rank=first_relevant_rank,
        top_k_accuracy=top_k_accuracy,
        precision_at_k=precision_at_k,
        recall_at_k=recall_at_k,
        mrr=mrr,
        entity_match_score=entity_match_score,
        explanation_coverage=explanation_coverage,
        negative_hit_count=negative_hit_count,
    )


def build_enterprise_search_report(
    *,
    user,
    results: list[EnterpriseSearchResult],
    top_k_values: tuple[int, ...] = DEFAULT_TOP_K,
) -> dict[str, Any]:
    total = len(results)
    metric_names = [str(k) for k in top_k_values]
    aggregate = {
        "total": total,
        "top_k_accuracy": {
            key: _average(1.0 if result.top_k_accuracy.get(key) else 0.0 for result in results)
            for key in metric_names
        },
        "precision_at_k": {
            key: _average(result.precision_at_k.get(key, 0.0) for result in results)
            for key in metric_names
        },
        "recall_at_k": {
            key: _average(result.recall_at_k.get(key, 0.0) for result in results)
            for key in metric_names
        },
        "mrr": _average(result.mrr for result in results),
        "entity_match_score": _average(result.entity_match_score for result in results),
        "explanation_coverage": _average(result.explanation_coverage for result in results),
        "negative_hit_count": sum(result.negative_hit_count for result in results),
    }
    return {
        "user": getattr(user, "username", ""),
        "metrics": aggregate,
        "results": [asdict(result) for result in results],
    }


def compare_enterprise_search_report(
    *,
    current_report: dict[str, Any],
    baseline_report: dict[str, Any],
    tolerance: float = 0.0,
) -> dict[str, Any]:
    regressions = []
    current_metrics = current_report.get("metrics", {})
    baseline_metrics = baseline_report.get("metrics", {})

    for family in ("top_k_accuracy", "precision_at_k", "recall_at_k"):
        for key, baseline_value in (baseline_metrics.get(family) or {}).items():
            current_value = (current_metrics.get(family) or {}).get(key, 0.0)
            if current_value + tolerance < baseline_value:
                regressions.append(
                    {
                        "metric": f"{family}.{key}",
                        "baseline": baseline_value,
                        "current": current_value,
                    }
                )

    for metric in ("mrr", "entity_match_score", "explanation_coverage"):
        baseline_value = baseline_metrics.get(metric, 0.0)
        current_value = current_metrics.get(metric, 0.0)
        if current_value + tolerance < baseline_value:
            regressions.append(
                {
                    "metric": metric,
                    "baseline": baseline_value,
                    "current": current_value,
                }
            )

    return {
        "regression_count": len(regressions),
        "regressions": regressions,
    }


def _serialize_ranked_document(*, rank: int, document: Document, score: float, reasons: list[str], search_query) -> dict[str, Any]:
    return {
        "rank": rank,
        "document_id": document.id,
        "title": document.title,
        "score": score,
        "document_type": document.search_entities.get("document_type", "") if document.search_entities else "",
        "entities": document.search_entities or {},
        "explanation": reasons,
        "snippet": build_search_snippet(document, search_query),
    }


def _document_matches_expected_labels(row: dict[str, Any], expected_labels: list[str]) -> bool:
    if not expected_labels:
        return False
    haystack = normalize_search_text(
        " ".join(
            [
                str(row.get("title", "")),
                str(row.get("document_type", "")),
                json.dumps(row.get("entities", {}), ensure_ascii=False),
            ]
        )
    )
    return any(normalize_search_text(label) in haystack for label in expected_labels)


def _entity_match_score(relevant_rows: list[dict[str, Any]], expected_entities: dict[str, Any]) -> float:
    if not expected_entities:
        return 1.0
    if not relevant_rows:
        return 0.0
    entities = relevant_rows[0].get("entities") or {}
    matched = 0
    total = 0
    for key, expected_value in expected_entities.items():
        total += 1
        actual_value = entities.get(key)
        if isinstance(expected_value, dict):
            expected_value = expected_value.get("value") or expected_value.get("raw") or expected_value
        if isinstance(actual_value, dict):
            actual_value = actual_value.get("value") or actual_value.get("raw") or actual_value
        if normalize_search_text(str(expected_value)) == normalize_search_text(str(actual_value)):
            matched += 1
    return round(matched / max(total, 1), 4)


def _explanation_coverage(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    explained = sum(1 for row in rows if row.get("explanation") or row.get("snippet"))
    return round(explained / len(rows), 4)


def _average(values) -> float:
    values = list(values)
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)
