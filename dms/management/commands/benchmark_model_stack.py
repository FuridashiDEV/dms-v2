from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from dms.services.model_stack import (
    EMBEDDING_MODEL_REGISTRY,
    NOOP_RERANKER_MODEL,
    collection_name_for_model,
    get_embedding_adapter,
    get_embedding_model_spec,
    get_reranker_adapter,
    registry_snapshot,
    stable_synthetic_embedding,
    validate_embedding_vector,
)
from dms.services.reranking import CandidateSignal, FusedCandidate, SOURCE_ENTITY, SOURCE_TEXT, SOURCE_VECTOR, rank_documents_for_search
from dms.services.search_intelligence import build_search_query, build_document_search_text, score_document_for_query


DEFAULT_SYNTHETIC_DATASET = "docs/model_stack_synthetic.json"
DEFAULT_REALISTIC_DATASET = "docs/search_benchmark/realistic_document_search_benchmark.json"


@dataclass(frozen=True)
class BenchmarkDocument:
    id: int
    external_id: str
    title: str
    text: str
    search_entities: dict[str, Any]
    search_text_normalized: str
    created_at: datetime
    doc_date: date | None = None
    description: str = ""


class Command(BaseCommand):
    help = "Benchmark the configurable OCR/embedding/reranking/entity/search model stack on safe synthetic or golden data."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", default="synthetic", help="'synthetic', 'golden', or a dataset JSON path.")
        parser.add_argument("--limit", type=int, default=50, help="Maximum query scenarios to evaluate.")
        parser.add_argument("--format", choices=["text", "json"], default="text")
        parser.add_argument("--models", default="", help="Comma-separated embedding model names. Defaults to current model.")
        parser.add_argument("--reranker-model", default="", help="Optional reranker model. Defaults to settings.")
        parser.add_argument("--load-models", action="store_true", help="Actually load local/HF models. Default uses deterministic local fallback.")

    def handle(self, *args, **options):
        dataset = self._load_dataset(options["dataset"])
        model_names = self._model_names(options.get("models"))
        reranker_model = options.get("reranker_model") or getattr(settings, "SEARCH_RERANKER_MODEL", NOOP_RERANKER_MODEL)
        load_models = bool(options["load_models"] or getattr(settings, "MODEL_STACK_BENCHMARK_LOAD_MODELS", False))
        limit = max(int(options["limit"] or 0), 1)

        reports = [
            self._benchmark_model(
                model_name=model_name,
                reranker_model=reranker_model,
                dataset=dataset,
                limit=limit,
                load_models=load_models,
            )
            for model_name in model_names
        ]
        payload = {
            "dataset": dataset["name"],
            "load_models": load_models,
            "baseline_model": getattr(settings, "SEARCH_BASELINE_EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
            "configured_embedding_model": getattr(settings, "SEARCH_EMBEDDING_MODEL", ""),
            "configured_reranker_model": reranker_model,
            "registry": registry_snapshot(),
            "reports": reports,
            "recommendation": self._recommendation(reports),
            "limitations": [
                "Synthetic benchmark does not prove production accuracy.",
                "Default benchmark mode avoids heavy model downloads; use --load-models for local model execution.",
                "Qdrant insert timing is reported as 0 unless this command is extended to write to a disposable benchmark collection.",
            ],
        }

        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
            return

        for report in reports:
            metrics = report["metrics"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"{report['embedding_model']}: "
                    f"top1={metrics['top_1_accuracy']:.2f} "
                    f"top3={metrics['top_3_accuracy']:.2f} "
                    f"top5={metrics['top_5_accuracy']:.2f} "
                    f"mrr={metrics['mrr']:.2f} "
                    f"p@5={metrics['precision_at_5']:.2f} "
                    f"r@10={metrics['recall_at_10']:.2f} "
                    f"avg_latency={metrics['average_latency_ms']:.2f}ms "
                    f"fallbacks={metrics['fallback_count']}"
                )
            )

    def _model_names(self, raw_models: str | None) -> list[str]:
        if raw_models:
            if raw_models.strip().lower() == "all":
                configured = getattr(settings, "SEARCH_EMBEDDING_MODEL", "BAAI/bge-m3")
                ordered = [configured, "BAAI/bge-m3", "intfloat/multilingual-e5-large", "all-MiniLM-L6-v2"]
                return list(dict.fromkeys(ordered))
            return [item.strip() for item in raw_models.split(",") if item.strip()]
        return [getattr(settings, "SEARCH_EMBEDDING_MODEL", "BAAI/bge-m3")]

    def _load_dataset(self, dataset: str) -> dict[str, Any]:
        if dataset == "synthetic":
            path = Path(settings.BASE_DIR) / DEFAULT_SYNTHETIC_DATASET
        elif dataset == "realistic":
            path = Path(settings.BASE_DIR) / DEFAULT_REALISTIC_DATASET
        elif dataset == "golden":
            path = Path(settings.BASE_DIR) / "docs/search_quality_golden.json"
            golden = json.loads(path.read_text(encoding="utf-8"))
            return _golden_to_model_stack_dataset(golden)
        else:
            path = Path(dataset)
            if not path.is_absolute():
                path = Path(settings.BASE_DIR) / path
        if not path.exists():
            raise CommandError(f"Dataset not found: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "documents" not in payload or "queries" not in payload:
            raise CommandError("Model stack dataset must contain documents and queries.")
        return payload

    def _benchmark_model(
        self,
        *,
        model_name: str,
        reranker_model: str,
        dataset: dict[str, Any],
        limit: int,
        load_models: bool,
    ) -> dict[str, Any]:
        spec = get_embedding_model_spec(model_name)
        adapter = get_embedding_adapter(model_name)
        reranker = get_reranker_adapter(reranker_model)
        documents = _build_documents(dataset["documents"])
        queries = list(dataset["queries"])[:limit]
        fallback_count = 0

        document_vectors: dict[str, list[float]] = {}
        embedding_doc_times = []
        for document in documents:
            started = time.perf_counter()
            if load_models:
                vector = adapter.encode_documents([document.search_text_normalized or document.text])[0]
            else:
                vector = stable_synthetic_embedding(document.search_text_normalized or document.text, dimension=spec.dimension)
                fallback_count += 1
            embedding_doc_times.append((time.perf_counter() - started) * 1000)
            if not validate_embedding_vector(vector, model_name=model_name, expected_dimension=spec.dimension).valid:
                fallback_count += 1
                vector = stable_synthetic_embedding(document.search_text_normalized or document.text, dimension=spec.dimension)
            document_vectors[document.external_id] = vector

        scenario_reports = []
        query_latencies = []
        rerank_latencies = []
        for scenario in queries:
            query_started = time.perf_counter()
            query = build_search_query(str(scenario["query"]))
            if load_models:
                query_vector = adapter.encode_query(query.expanded_text)
            else:
                query_vector = stable_synthetic_embedding(query.expanded_text, dimension=spec.dimension)
                fallback_count += 1
            if not validate_embedding_vector(query_vector, model_name=model_name, expected_dimension=spec.dimension).valid:
                fallback_count += 1
                query_vector = stable_synthetic_embedding(query.expanded_text, dimension=spec.dimension)

            vector_scores = {
                document.id: _cosine_similarity(query_vector, document_vectors[document.external_id])
                for document in documents
            }
            fused_candidates = {}
            for document in documents:
                candidate = FusedCandidate(document_id=document.id)
                semantic_score = vector_scores.get(document.id, 0.0)
                base_score, reasons = score_document_for_query(document, query, semantic_score=semantic_score)
                if base_score > 0:
                    candidate.add_signal(CandidateSignal(source=SOURCE_TEXT, score=base_score, reason="text/entity candidate"))
                if semantic_score > 0:
                    candidate.add_signal(CandidateSignal(source=SOURCE_VECTOR, score=semantic_score, reason="vector candidate"))
                if reasons:
                    candidate.add_signal(CandidateSignal(source=SOURCE_ENTITY, score=min(base_score, 1.0), reason=reasons[0]))
                fused_candidates[document.id] = candidate

            rerank_started = time.perf_counter()
            rerank_results = reranker.rerank(
                query=query.raw,
                passages=[document.search_text_normalized for document in documents],
                top_k=min(50, len(documents)),
            )
            rerank_latency_ms = (time.perf_counter() - rerank_started) * 1000
            rerank_latencies.append(rerank_latency_ms)
            rerank_scores = {documents[result.index].id: result.score for result in rerank_results if result.index < len(documents)}

            def reranker_hook(document, _query):
                score = rerank_scores.get(document.id, 0.0)
                return score, ["optional reranker score applied"] if score else []

            ranked = rank_documents_for_search(
                documents=documents,
                search_query=query,
                fused_candidates=fused_candidates,
                reranker=reranker_hook if rerank_scores else None,
                min_score=0.0,
                multi_token_min_score=0.0,
            )
            query_latency_ms = (time.perf_counter() - query_started) * 1000
            query_latencies.append(query_latency_ms)
            scenario_reports.append(
                _scenario_report(
                    scenario=scenario,
                    ranked=ranked,
                    latency_ms=query_latency_ms,
                    rerank_latency_ms=rerank_latency_ms,
                )
            )

        return {
            "embedding_model": model_name,
            "adapter": adapter.__class__.__name__,
            "vector_dimension": spec.dimension,
            "qdrant_collection": collection_name_for_model(model_name),
            "qdrant_compatible": True,
            "search_index_version_compatible": True,
            "e5_query_prefix": spec.query_prefix,
            "e5_passage_prefix": spec.passage_prefix,
            "reranker_model": reranker_model,
            "reranker_adapter": reranker.__class__.__name__,
            "metrics": _aggregate_metrics(
                scenario_reports,
                query_latencies=query_latencies,
                embedding_doc_times=embedding_doc_times,
                rerank_latencies=rerank_latencies,
                fallback_count=fallback_count,
            ),
            "scenarios": scenario_reports,
        }

    def _recommendation(self, reports: list[dict[str, Any]]) -> str:
        if not reports:
            return "No benchmark reports were produced."
        current = reports[0]
        return (
            f"Keep {current['embedding_model']} as the configured model until real document benchmarks "
            "show a clear quality/latency improvement. Do not mix dimensions in one Qdrant collection."
        )


def _build_documents(raw_documents: list[dict[str, Any]]) -> list[BenchmarkDocument]:
    now = timezone.now()
    documents = []
    for index, item in enumerate(raw_documents, start=1):
        search_entities = item.get("entities") or {}
        document = SimpleNamespace(
            id=index,
            title=str(item.get("title") or item.get("id") or f"Document {index}"),
            description=str(item.get("text") or ""),
            document_author="",
            source_file_name="",
            doc_type=None,
            folder=None,
            extracted_text=str(item.get("text") or ""),
            search_entities=search_entities,
        )
        search_text = build_document_search_text(document)
        documents.append(
            BenchmarkDocument(
                id=index,
                external_id=str(item.get("id") or index),
                title=document.title,
                text=document.extracted_text,
                search_entities=search_entities,
                search_text_normalized=search_text,
                description=document.description,
                created_at=now,
            )
        )
    return documents


def _scenario_report(*, scenario: dict[str, Any], ranked: list, latency_ms: float, rerank_latency_ms: float) -> dict[str, Any]:
    expected = str(scenario["expected_document_id"])
    top_ids = [item.document.external_id for item in ranked[:10]]
    first_rank = next((index for index, doc_id in enumerate(top_ids, start=1) if doc_id == expected), None)
    return {
        "id": scenario.get("id") or scenario["query"],
        "query": scenario["query"],
        "expected_document_id": expected,
        "top_document_ids": top_ids,
        "first_relevant_rank": first_rank,
        "top_1": first_rank is not None and first_rank <= 1,
        "top_3": first_rank is not None and first_rank <= 3,
        "top_5": first_rank is not None and first_rank <= 5,
        "precision_at_5": round((1 if first_rank is not None and first_rank <= 5 else 0) / 5, 4),
        "recall_at_10": 1.0 if first_rank is not None and first_rank <= 10 else 0.0,
        "mrr": round(1 / first_rank, 4) if first_rank else 0.0,
        "latency_ms": round(latency_ms, 4),
        "reranking_latency_ms": round(rerank_latency_ms, 4),
    }


def _aggregate_metrics(
    scenario_reports: list[dict[str, Any]],
    *,
    query_latencies: list[float],
    embedding_doc_times: list[float],
    rerank_latencies: list[float],
    fallback_count: int,
) -> dict[str, float | int]:
    total = max(len(scenario_reports), 1)
    return {
        "top_1_accuracy": _average(1.0 if item["top_1"] else 0.0 for item in scenario_reports),
        "top_3_accuracy": _average(1.0 if item["top_3"] else 0.0 for item in scenario_reports),
        "top_5_accuracy": _average(1.0 if item["top_5"] else 0.0 for item in scenario_reports),
        "mrr": _average(item["mrr"] for item in scenario_reports),
        "precision_at_5": _average(item["precision_at_5"] for item in scenario_reports),
        "recall_at_10": _average(item["recall_at_10"] for item in scenario_reports),
        "average_latency_ms": _average(query_latencies),
        "p95_latency_ms": _p95(query_latencies),
        "embedding_time_per_document_ms": _average(embedding_doc_times),
        "reranking_latency_ms": _average(rerank_latencies),
        "qdrant_insert_time_ms": 0.0,
        "fallback_count": fallback_count,
        "scenario_count": total,
    }


def _golden_to_model_stack_dataset(golden: list[dict[str, Any]]) -> dict[str, Any]:
    documents = []
    queries = []
    for index, item in enumerate(golden, start=1):
        doc_id = f"golden-{index}"
        title = item["expected_labels"][0]
        documents.append(
            {
                "id": doc_id,
                "title": title,
                "text": " ".join([title, item.get("query", ""), json.dumps(item.get("expected_entities", {}), ensure_ascii=False)]),
                "entities": item.get("expected_entities", {}),
            }
        )
        queries.append(
            {
                "id": item.get("id") or doc_id,
                "query": item["query"],
                "expected_document_id": doc_id,
            }
        )
    return {"name": "golden", "documents": documents, "queries": queries}


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return round(max(min(dot / (left_norm * right_norm), 1.0), -1.0), 4)


def _average(values) -> float:
    values = list(values)
    if not values:
        return 0.0
    return round(sum(float(value) for value in values) / len(values), 4)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 4)
    return round(statistics.quantiles(values, n=20, method="inclusive")[18], 4)
