from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterable

from django.conf import settings

from dms.services.model_stack import get_reranker_adapter
from dms.services.search_intelligence import SearchQuery, score_document_for_query


SOURCE_EXACT = "exact"
SOURCE_ENTITY = "entity"
SOURCE_TEXT = "text"
SOURCE_ALIAS = "alias"
SOURCE_VECTOR = "vector"
SOURCE_RELATED = "related"

SOURCE_WEIGHTS = {
    SOURCE_EXACT: 0.34,
    SOURCE_ENTITY: 0.3,
    SOURCE_TEXT: 0.22,
    SOURCE_ALIAS: 0.18,
    SOURCE_VECTOR: 0.26,
    SOURCE_RELATED: 0.1,
}


@dataclass
class CandidateSignal:
    source: str
    rank: int = 1
    score: float = 0.0
    reason: str = ""


@dataclass
class FusedCandidate:
    document_id: int
    signals: list[CandidateSignal] = field(default_factory=list)

    def add_signal(self, signal: CandidateSignal) -> None:
        self.signals.append(signal)

    @property
    def sources(self) -> set[str]:
        return {signal.source for signal in self.signals}

    @property
    def fusion_score(self) -> float:
        score = 0.0
        for signal in self.signals:
            weight = SOURCE_WEIGHTS.get(signal.source, 0.12)
            reciprocal_rank = 1 / (60 + max(signal.rank, 1))
            score += weight * reciprocal_rank
            if signal.score:
                score += weight * min(max(signal.score, 0.0), 1.0) * 0.35
        return round(score, 4)


@dataclass
class RankedSearchResult:
    document: object
    final_score: float
    confidence: float
    reasons: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


RerankerHook = Callable[[object, SearchQuery], tuple[float, list[str]] | float]


def configured_reranker_hook() -> RerankerHook | None:
    if not getattr(settings, "SEARCH_RERANKER_ENABLED", False):
        return None
    adapter = get_reranker_adapter(getattr(settings, "SEARCH_RERANKER_MODEL", "noop"))

    def _hook(document: object, search_query: SearchQuery) -> tuple[float, list[str]]:
        passages = [
            " ".join(
                filter(
                    None,
                    [
                        getattr(document, "title", ""),
                        getattr(document, "description", ""),
                        getattr(document, "search_text_normalized", ""),
                    ],
                )
            )
        ]
        results = adapter.rerank(query=search_query.raw, passages=passages, top_k=1)
        if not results:
            return 0.0, ["optional reranker unavailable"]
        result = results[0]
        return result.score, [result.reason or "optional reranker score applied"]

    return _hook


def fuse_candidates(
    *,
    text_ids: Iterable[int] = (),
    vector_scores: dict[int, float] | None = None,
    exact_ids: Iterable[int] = (),
    entity_ids: Iterable[int] = (),
    alias_ids: Iterable[int] = (),
    related_ids: Iterable[int] = (),
) -> dict[int, FusedCandidate]:
    candidates: dict[int, FusedCandidate] = {}

    def add_many(ids: Iterable[int], source: str, reason: str) -> None:
        for rank, document_id in enumerate(ids, start=1):
            candidate = candidates.setdefault(document_id, FusedCandidate(document_id=document_id))
            candidate.add_signal(CandidateSignal(source=source, rank=rank, reason=reason))

    add_many(exact_ids, SOURCE_EXACT, "exact/entity candidate")
    add_many(entity_ids, SOURCE_ENTITY, "structured entity candidate")
    add_many(text_ids, SOURCE_TEXT, "text candidate")
    add_many(alias_ids, SOURCE_ALIAS, "alias candidate")
    add_many(related_ids, SOURCE_RELATED, "related document candidate")

    for rank, (document_id, score) in enumerate((vector_scores or {}).items(), start=1):
        candidate = candidates.setdefault(document_id, FusedCandidate(document_id=document_id))
        candidate.add_signal(
            CandidateSignal(
                source=SOURCE_VECTOR,
                rank=rank,
                score=score,
                reason="vector candidate",
            )
        )
    return candidates


def rank_documents_for_search(
    *,
    documents: Iterable[object],
    search_query: SearchQuery,
    fused_candidates: dict[int, FusedCandidate],
    reranker: RerankerHook | None = None,
    min_score: float = 0.18,
    multi_token_min_score: float = 0.24,
) -> list[RankedSearchResult]:
    ranked: list[RankedSearchResult] = []
    query_token_count = len(search_query.tokens)
    for document in documents:
        candidate = fused_candidates.get(document.id, FusedCandidate(document_id=document.id))
        semantic_score = _max_source_score(candidate, SOURCE_VECTOR)
        base_score, base_reasons = score_document_for_query(
            document,
            search_query,
            semantic_score=semantic_score,
        )
        reranker_score, reranker_reasons = _run_optional_reranker(reranker, document, search_query)
        final_score = calculate_final_score(
            base_score=base_score,
            fusion_score=candidate.fusion_score,
            reranker_score=reranker_score,
        )

        if semantic_score < 0.2 and final_score < min_score:
            continue
        if query_token_count >= 2 and final_score < multi_token_min_score:
            continue

        confidence = calculate_confidence(
            final_score=final_score,
            source_count=len(candidate.sources),
            reason_count=len(base_reasons) + len(reranker_reasons),
        )
        reasons = build_explanation_reasons(
            candidate=candidate,
            base_reasons=base_reasons,
            reranker_reasons=reranker_reasons,
            final_score=final_score,
            confidence=confidence,
        )
        ranked.append(
            RankedSearchResult(
                document=document,
                final_score=final_score,
                confidence=confidence,
                reasons=reasons,
                sources=sorted(candidate.sources),
            )
        )

    ranked.sort(
        key=lambda item: (
            item.final_score,
            item.confidence,
            item.document.doc_date or date.min,
            item.document.created_at,
        ),
        reverse=True,
    )
    return ranked


def calculate_final_score(*, base_score: float, fusion_score: float, reranker_score: float = 0.0) -> float:
    weighted_score = base_score * 0.72 + min(fusion_score, 1.0) * 0.22 + reranker_score * 0.06
    score = max(base_score, weighted_score)
    return round(min(max(score, 0.0), 1.25), 4)


def calculate_confidence(*, final_score: float, source_count: int, reason_count: int) -> float:
    source_bonus = min(source_count, 4) * 0.06
    reason_bonus = min(reason_count, 5) * 0.025
    return round(min(max(final_score * 0.72 + source_bonus + reason_bonus, 0.0), 1.0), 4)


def build_explanation_reasons(
    *,
    candidate: FusedCandidate,
    base_reasons: list[str],
    reranker_reasons: list[str],
    final_score: float,
    confidence: float,
) -> list[str]:
    reasons = []
    source_labels = sorted(candidate.sources)
    if source_labels:
        reasons.append("candidate sources: " + ", ".join(source_labels))
    for signal in candidate.signals[:4]:
        if signal.reason:
            reasons.append(signal.reason)
    reasons.extend(base_reasons)
    reasons.extend(reranker_reasons)
    final_reason = f"final score {final_score:.2f}, confidence {confidence:.2f}"
    deduped = list(dict.fromkeys(reason for reason in reasons if reason))
    if final_reason in deduped:
        deduped.remove(final_reason)
    return [*deduped[:7], final_reason]


def _max_source_score(candidate: FusedCandidate, source: str) -> float:
    scores = [signal.score for signal in candidate.signals if signal.source == source]
    return max(scores) if scores else 0.0


def _run_optional_reranker(
    reranker: RerankerHook | None,
    document: object,
    search_query: SearchQuery,
) -> tuple[float, list[str]]:
    if not reranker:
        return 0.0, []
    try:
        result = reranker(document, search_query)
    except Exception:
        return 0.0, ["optional reranker unavailable"]
    if isinstance(result, tuple):
        score, reasons = result
        return min(max(float(score or 0.0), 0.0), 1.0), list(reasons or [])
    return min(max(float(result or 0.0), 0.0), 1.0), ["optional reranker score applied"]
