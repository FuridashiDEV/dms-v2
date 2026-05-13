from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Q, QuerySet

from dms.models import Document, DocumentRelation
from dms.services.search_intelligence import SearchQuery, normalize_search_text


SEARCH_MODE_HYBRID = "hybrid"
SEARCH_MODE_EXACT = "exact"
SEARCH_MODE_SEMANTIC = "semantic"
SEARCH_MODES = {SEARCH_MODE_HYBRID, SEARCH_MODE_EXACT, SEARCH_MODE_SEMANTIC}


@dataclass
class SearchQualityCase:
    query: str
    expected_title_contains: str = ""


@dataclass
class SearchQualityResult:
    query: str
    expected_title_contains: str
    matched: bool
    top_titles: list[str] = field(default_factory=list)


def normalize_search_mode(value: str | None) -> str:
    return value if value in SEARCH_MODES else SEARCH_MODE_HYBRID


def apply_experience_filters(
    queryset: QuerySet,
    *,
    counterparty: str = "",
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
) -> QuerySet:
    normalized_counterparty = normalize_search_text(counterparty)
    if normalized_counterparty:
        queryset = queryset.filter(
            Q(search_entities__counterparty__icontains=normalized_counterparty)
            | Q(search_text_normalized__icontains=normalized_counterparty)
            | Q(title__icontains=counterparty)
            | Q(description__icontains=counterparty)
            | Q(document_author__icontains=counterparty)
        )

    if amount_min is not None:
        queryset = queryset.filter(search_entities__amount__value__gte=int(amount_min))
    if amount_max is not None:
        queryset = queryset.filter(search_entities__amount__value__lte=int(amount_max))

    return queryset


def build_lexical_filter(raw_query: str, search_query: SearchQuery) -> Q:
    entity_values: list[str] = []
    for key in ("document_type", "counterparty", "subject"):
        if search_query.entities.get(key):
            entity_values.append(str(search_query.entities[key]))
    if search_query.entities.get("amount", {}).get("raw"):
        entity_values.append(str(search_query.entities["amount"]["raw"]))

    lexical_filter = (
        Q(title__icontains=raw_query)
        | Q(description__icontains=raw_query)
        | Q(extracted_text__icontains=raw_query)
        | Q(document_author__icontains=raw_query)
        | Q(source_file_name__icontains=raw_query)
        | Q(public_id__icontains=raw_query)
        | Q(doc_type__name__icontains=raw_query)
        | Q(folder__name__icontains=raw_query)
        | Q(department__name__icontains=raw_query)
        | Q(search_text_normalized__icontains=search_query.normalized)
    )
    for token in [*search_query.tokens, *entity_values]:
        lexical_filter |= (
            Q(title__icontains=token)
            | Q(description__icontains=token)
            | Q(extracted_text__icontains=token)
            | Q(document_author__icontains=token)
            | Q(source_file_name__icontains=token)
            | Q(doc_type__name__icontains=token)
            | Q(folder__name__icontains=token)
            | Q(department__name__icontains=token)
            | Q(search_text_normalized__icontains=token)
        )
    return lexical_filter


def build_search_snippet(document: Document, search_query: SearchQuery | None, *, radius: int = 110) -> str:
    if not search_query:
        return ""

    source = " ".join(
        part
        for part in [
            document.description,
            document.extracted_text,
            document.title,
            document.source_file_name,
        ]
        if part
    )
    source = " ".join(source.split())
    if not source:
        return ""

    lowered = source.lower()
    terms = [search_query.normalized, *search_query.tokens]
    for values in search_query.aliases.values():
        terms.extend(values)

    hit_index = -1
    for term in terms:
        term = (term or "").strip().lower()
        if len(term) < 2:
            continue
        hit_index = lowered.find(term)
        if hit_index >= 0:
            break

    if hit_index < 0:
        return source[: radius * 2].strip()

    start = max(hit_index - radius, 0)
    end = min(hit_index + radius, len(source))
    prefix = "... " if start else ""
    suffix = " ..." if end < len(source) else ""
    return f"{prefix}{source[start:end].strip()}{suffix}"


def matched_entities_for_document(document: Document, search_query: SearchQuery | None) -> list[str]:
    if not search_query:
        return []

    document_entities = document.search_entities or {}
    query_entities = search_query.entities or {}
    matched = []
    for key in ("document_type", "counterparty", "subject"):
        value = query_entities.get(key)
        if value and str(value) in normalize_search_text(str(document_entities.get(key, ""))):
            matched.append(f"{key}: {value}")

    query_amount = query_entities.get("amount") or {}
    document_amount = document_entities.get("amount") or {}
    if query_amount.get("value") and query_amount.get("value") == document_amount.get("value"):
        matched.append(f"amount: {query_amount.get('raw')}")

    return matched


def accessible_related_documents_for_search(
    document: Document,
    allowed_documents: QuerySet,
    *,
    limit: int = 3,
) -> list[dict]:
    allowed_ids = set(allowed_documents.values_list("id", flat=True))
    if not allowed_ids:
        return []

    relations = (
        DocumentRelation.objects
        .filter(Q(from_document=document) | Q(to_document=document))
        .select_related("from_document", "to_document")
        .order_by("-created_at")[:20]
    )
    related = []
    seen = set()
    for relation in relations:
        target = relation.to_document if relation.from_document_id == document.id else relation.from_document
        if target.id in seen or target.id not in allowed_ids:
            continue
        seen.add(target.id)
        related.append(
            {
                "document": target,
                "relation_type": relation.get_relation_type_display(),
            }
        )
        if len(related) >= limit:
            break
    return related


def evaluate_search_quality(
    *,
    user,
    cases: list[SearchQualityCase],
    queryset: QuerySet,
    limit: int = 5,
) -> dict:
    from dms.services.search_intelligence import build_search_query, score_document_for_query

    results = []
    matched_count = 0
    for case in cases:
        search_query = build_search_query(case.query)
        scored = []
        for document in queryset:
            score, _ = score_document_for_query(document, search_query, semantic_score=0.0)
            if score > 0:
                scored.append((score, document))
        scored.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
        top_titles = [document.title for _, document in scored[:limit]]
        expected = case.expected_title_contains.lower()
        matched = bool(expected) and any(expected in title.lower() for title in top_titles)
        if matched:
            matched_count += 1
        results.append(
            SearchQualityResult(
                query=case.query,
                expected_title_contains=case.expected_title_contains,
                matched=matched,
                top_titles=top_titles,
            )
        )

    total = len(cases)
    return {
        "user": user.username,
        "total": total,
        "matched": matched_count,
        "precision_at_limit": matched_count / total if total else 0,
        "results": results,
    }
