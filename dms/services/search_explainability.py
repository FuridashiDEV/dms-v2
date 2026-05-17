from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import re
from typing import Iterable

from dms.models import Document
from dms.services.search_experience import build_search_snippet, matched_entities_for_document
from dms.services.search_intelligence import SearchQuery, normalize_search_text


SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(token|secret|password|api[_ -]?key|authorization|bearer)\s*[:=]\s*[\w\-.:/+=]+"),
    re.compile(r"(?i)(secure[_ -]?token|access[_ -]?token|refresh[_ -]?token)\s*[:=]\s*[\w\-.:/+=]+"),
)
SENSITIVE_WORDS = {
    "payload",
    "secure_token",
    "access_token",
    "refresh_token",
    "authorization",
    "password",
    "secret",
    "api_key",
}


@dataclass
class MatchedChunk:
    field: str
    snippet: str
    matched_terms: list[str] = field(default_factory=list)


@dataclass
class SearchExplanation:
    matched_entities: list[str] = field(default_factory=list)
    matched_aliases: list[str] = field(default_factory=list)
    matched_chunks: list[MatchedChunk] = field(default_factory=list)
    matched_filters: list[str] = field(default_factory=list)
    semantic_score: float = 0.0
    entity_score: float = 0.0
    final_score: float = 0.0
    confidence: float = 0.0
    human_readable_reasons: list[str] = field(default_factory=list)
    candidate_sources: list[str] = field(default_factory=list)


def build_search_explanation(
    *,
    document: Document,
    search_query: SearchQuery | None,
    semantic_score: float = 0.0,
    final_score: float = 0.0,
    confidence: float = 0.0,
    candidate_sources: Iterable[str] = (),
    base_reasons: Iterable[str] = (),
    filters: dict | None = None,
) -> SearchExplanation:
    if search_query is None:
        return SearchExplanation()

    matched_entities = _safe_list(matched_entities_for_document(document, search_query), limit=8)
    matched_aliases = _matched_aliases(document, search_query)
    matched_chunks = _matched_chunks(document, search_query)
    matched_filters = _matched_filters(document, filters or {})
    entity_score = _entity_score(matched_entities, search_query)
    safe_reasons = _safe_list(base_reasons, limit=6)

    human_reasons = _build_human_reasons(
        matched_entities=matched_entities,
        matched_aliases=matched_aliases,
        matched_chunks=matched_chunks,
        matched_filters=matched_filters,
        semantic_score=semantic_score,
        entity_score=entity_score,
        final_score=final_score,
        confidence=confidence,
        base_reasons=safe_reasons,
    )

    return SearchExplanation(
        matched_entities=matched_entities,
        matched_aliases=matched_aliases,
        matched_chunks=matched_chunks,
        matched_filters=matched_filters,
        semantic_score=_bounded_score(semantic_score),
        entity_score=entity_score,
        final_score=round(float(final_score or 0.0), 4),
        confidence=_bounded_score(confidence),
        human_readable_reasons=human_reasons,
        candidate_sources=_safe_list(candidate_sources, limit=6),
    )


def sanitize_explanation_value(value: object, *, max_length: int = 180) -> str:
    cleaned = " ".join(str(value or "").split())
    for pattern in SENSITIVE_PATTERNS:
        cleaned = pattern.sub(lambda match: f"{match.group(1)}: [redacted]", cleaned)
    for word in SENSITIVE_WORDS:
        cleaned = re.sub(rf"(?i)\b{re.escape(word)}\b", "[redacted]", cleaned)
    if len(cleaned) > max_length:
        cleaned = cleaned[: max_length - 3].rstrip() + "..."
    return cleaned


def _matched_aliases(document: Document, search_query: SearchQuery) -> list[str]:
    text = _document_search_text(document)
    matches = []
    for source, variants in (search_query.aliases or {}).items():
        values = [str(source), *[str(value) for value in variants]]
        hit_values = [value for value in values if value and normalize_search_text(value) in text]
        if hit_values:
            display = f"{source} -> {', '.join(dict.fromkeys(hit_values[1:3] or hit_values[:2]))}"
            matches.append(sanitize_explanation_value(display, max_length=120))
    return list(dict.fromkeys(matches))[:6]


def _matched_chunks(document: Document, search_query: SearchQuery) -> list[MatchedChunk]:
    terms = _query_terms(search_query)
    if not terms:
        return []

    chunks = []
    for field_name, value in (
        ("title", document.title),
        ("description", document.description),
        ("text", document.extracted_text),
        ("file", document.source_file_name),
    ):
        source = " ".join(str(value or "").split())
        normalized_source = normalize_search_text(source)
        matched_terms = [term for term in terms if term and term in normalized_source]
        if not matched_terms:
            continue
        snippet = build_search_snippet(document, search_query) if field_name == "text" else source[:220]
        snippet = sanitize_explanation_value(snippet, max_length=240)
        if snippet:
            chunks.append(
                MatchedChunk(
                    field=field_name,
                    snippet=snippet,
                    matched_terms=_safe_list(matched_terms, limit=5, max_length=60),
                )
            )
        if len(chunks) >= 3:
            break
    return chunks


def _matched_filters(document: Document, filters: dict) -> list[str]:
    matched = []
    if filters.get("doc_type") and document.doc_type:
        matched.append(f"type: {document.doc_type.name}")
    if filters.get("department") and document.department:
        matched.append(f"department: {document.department.name}")
    if filters.get("folder") and document.folder:
        matched.append(f"folder: {document.folder.name}")
    if filters.get("counterparty"):
        matched.append(f"counterparty filter: {filters['counterparty']}")
    if filters.get("amount_min") is not None or filters.get("amount_max") is not None:
        matched.append(_amount_filter_label(filters.get("amount_min"), filters.get("amount_max")))
    if filters.get("status"):
        matched.append(f"status: {filters['status']}")
    if filters.get("date_from") or filters.get("date_to"):
        matched.append(_date_filter_label(filters.get("date_from"), filters.get("date_to")))
    return _safe_list(matched, limit=8)


def _build_human_reasons(
    *,
    matched_entities: list[str],
    matched_aliases: list[str],
    matched_chunks: list[MatchedChunk],
    matched_filters: list[str],
    semantic_score: float,
    entity_score: float,
    final_score: float,
    confidence: float,
    base_reasons: list[str],
) -> list[str]:
    reasons = []
    if matched_entities:
        reasons.append("matched structured entities: " + ", ".join(matched_entities[:3]))
    if matched_aliases:
        reasons.append("matched alias variants: " + ", ".join(matched_aliases[:2]))
    if matched_chunks:
        reasons.append("matched document fragment: " + matched_chunks[0].snippet)
    if matched_filters:
        reasons.append("matched active filters: " + ", ".join(matched_filters[:3]))
    if semantic_score:
        reasons.append(f"semantic similarity score {float(semantic_score):.2f}")
    if entity_score:
        reasons.append(f"entity match score {entity_score:.2f}")
    reasons.extend(base_reasons)
    reasons.append(f"final score {float(final_score or 0.0):.2f}, confidence {float(confidence or 0.0):.2f}")
    return list(dict.fromkeys(_safe_list(reasons, limit=8, max_length=240)))


def _entity_score(matched_entities: list[str], search_query: SearchQuery) -> float:
    query_entities = search_query.entities or {}
    possible = 0
    for key, value in query_entities.items():
        if isinstance(value, dict):
            possible += 1 if any(value.values()) else 0
        elif isinstance(value, list):
            possible += 1 if value else 0
        elif value:
            possible += 1
    if not possible:
        return 0.0
    return round(min(len(matched_entities) / possible, 1.0), 4)


def _query_terms(search_query: SearchQuery) -> list[str]:
    terms = [search_query.normalized, *search_query.tokens]
    for values in (search_query.aliases or {}).values():
        terms.extend(str(value) for value in values if value)
    for value in (search_query.entities or {}).values():
        if isinstance(value, dict):
            terms.extend(str(item) for item in value.values() if item)
        elif isinstance(value, list):
            terms.extend(str(item) for item in value if item)
        elif value:
            terms.append(str(value))
    normalized = [normalize_search_text(term) for term in terms if term]
    return [term for term in dict.fromkeys(normalized) if len(term) >= 2][:40]


def _document_search_text(document: Document) -> str:
    values = [
        document.search_text_normalized,
        document.title,
        document.description,
        document.extracted_text,
        document.source_file_name,
    ]
    return normalize_search_text(" ".join(str(value) for value in values if value))


def _safe_list(values: Iterable[object], *, limit: int, max_length: int = 180) -> list[str]:
    safe = []
    for value in values or []:
        cleaned = sanitize_explanation_value(value, max_length=max_length)
        if cleaned:
            safe.append(cleaned)
    return list(dict.fromkeys(safe))[:limit]


def _bounded_score(value: float) -> float:
    return round(min(max(float(value or 0.0), 0.0), 1.0), 4)


def _amount_filter_label(amount_min: Decimal | None, amount_max: Decimal | None) -> str:
    if amount_min is not None and amount_max is not None:
        return f"amount: {amount_min}..{amount_max}"
    if amount_min is not None:
        return f"amount >= {amount_min}"
    return f"amount <= {amount_max}"


def _date_filter_label(date_from, date_to) -> str:
    if date_from and date_to:
        return f"date: {date_from}..{date_to}"
    if date_from:
        return f"date >= {date_from}"
    return f"date <= {date_to}"
