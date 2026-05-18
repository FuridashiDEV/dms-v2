from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from urllib.parse import urlencode

from django.db.models import Q, QuerySet

from dms.models import Document, DocumentRelation, DocumentSearchIndexState
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


@dataclass
class SearchSuggestion:
    label: str
    description: str
    querystring: str


@dataclass
class SearchModeExplanation:
    mode: str
    label: str
    description: str
    is_active: bool = False


def normalize_search_mode(value: str | None) -> str:
    return value if value in SEARCH_MODES else SEARCH_MODE_HYBRID


def search_mode_explanations(active_mode: str) -> list[SearchModeExplanation]:
    active_mode = normalize_search_mode(active_mode)
    return [
        SearchModeExplanation(
            mode=SEARCH_MODE_HYBRID,
            label="Hybrid",
            description="Combines exact fields, extracted entities, aliases, text and semantic candidates.",
            is_active=active_mode == SEARCH_MODE_HYBRID,
        ),
        SearchModeExplanation(
            mode=SEARCH_MODE_EXACT,
            label="Exact",
            description="Best for document numbers, file names, titles and strict archive fields.",
            is_active=active_mode == SEARCH_MODE_EXACT,
        ),
        SearchModeExplanation(
            mode=SEARCH_MODE_SEMANTIC,
            label="Semantic",
            description="Uses meaning-based candidates when the vector index is available, with safe text fallback.",
            is_active=active_mode == SEARCH_MODE_SEMANTIC,
        ),
    ]


def confidence_badge(confidence: float | None) -> dict:
    if confidence is None:
        return {
            "label": "Not scored",
            "level": "unknown",
            "note": "Shown by archive ordering or filters.",
        }
    confidence = float(confidence or 0)
    if confidence >= 0.72:
        return {
            "label": "High confidence",
            "level": "high",
            "note": "Several search signals agree.",
        }
    if confidence >= 0.42:
        return {
            "label": "Medium confidence",
            "level": "medium",
            "note": "Some relevant signals matched.",
        }
    return {
        "label": "Low confidence",
        "level": "low",
        "note": "Review the card before relying on it.",
    }


def build_search_readiness(document: Document) -> list[dict]:
    states = _document_index_states(document)
    has_indexed_state = any(state.status == DocumentSearchIndexState.Status.INDEXED for state in states)
    has_failed_state = any(state.status == DocumentSearchIndexState.Status.FAILED for state in states)
    has_pending_state = any(
        state.status in {DocumentSearchIndexState.Status.PENDING, DocumentSearchIndexState.Status.STALE}
        for state in states
    )
    has_file = bool(getattr(document, "file", None))
    has_basic_text = bool(document.search_text_normalized or document.title or document.source_file_name)
    has_extracted_text = bool((document.extracted_text or "").strip())

    readiness = [
        {
            "key": "uploaded",
            "label": "Uploaded",
            "state": "ready" if has_file else "missing",
            "note": "Document record exists." if has_file else "File is missing.",
        },
        {
            "key": "basic",
            "label": "Basic search",
            "state": "ready" if has_basic_text else "pending",
            "note": "Title and metadata are searchable." if has_basic_text else "Waiting for basic metadata.",
        },
        {
            "key": "text",
            "label": "Text extracted",
            "state": "ready" if has_extracted_text else "pending",
            "note": "Full-text snippets can be shown." if has_extracted_text else "Text extraction may still be pending.",
        },
    ]

    if has_failed_state:
        readiness.append(
            {
                "key": "processing_failed",
                "label": "Processing failed",
                "state": "failed",
                "note": "Semantic index needs attention.",
            }
        )
    elif has_indexed_state or document.search_indexed_at:
        readiness.append(
            {
                "key": "semantic_ready",
                "label": "Semantic ready",
                "state": "ready",
                "note": "Vector search can use this document.",
            }
        )
    else:
        readiness.append(
            {
                "key": "semantic_pending",
                "label": "Semantic pending",
                "state": "pending" if has_pending_state or has_extracted_text or has_basic_text else "missing",
                "note": "Document can still appear through filters and text search.",
            }
        )
    return readiness


def build_search_suggestions(
    search_query: SearchQuery | None,
    current_params,
    *,
    max_items: int = 4,
) -> list[SearchSuggestion]:
    suggestions: list[SearchSuggestion] = []

    def add(label: str, description: str, **updates) -> None:
        params = _query_params_with_updates(current_params, **updates)
        querystring = urlencode(params, doseq=True)
        candidate = SearchSuggestion(label=label, description=description, querystring=querystring)
        if candidate.querystring and candidate.querystring not in {item.querystring for item in suggestions}:
            suggestions.append(candidate)

    if search_query:
        entities = search_query.entities or {}
        counterparty = entities.get("counterparty")
        if counterparty:
            add("Search this counterparty", "Narrow results to the detected counterparty.", q=counterparty, counterparty=counterparty, search_mode=SEARCH_MODE_HYBRID)
        amount = entities.get("amount") or {}
        amount_value = amount.get("value")
        if amount_value:
            lower = max(int(amount_value * 0.9), 0)
            upper = int(amount_value * 1.1)
            add("Search around this amount", "Use a practical amount range instead of an exact phrase.", amount_min=lower, amount_max=upper, search_mode=SEARCH_MODE_HYBRID)
        document_type = entities.get("document_type")
        if document_type:
            add("Search this document type", "Keep the detected document type as the main term.", q=document_type, search_mode=SEARCH_MODE_HYBRID)
        for key, values in (search_query.aliases or {}).items():
            if values:
                add("Try alias variants", "Use normalized aliases for spelling or language variants.", q=" ".join(values[:4]), search_mode=SEARCH_MODE_HYBRID)
                break

    if len(suggestions) < max_items:
        add("Search by counterparty", "Example: contract with IP Firma.", q="contract IP Firma", search_mode=SEARCH_MODE_HYBRID)
    if len(suggestions) < max_items:
        add("Search by amount", "Example: invoice for 3 mln KZT.", q="invoice 3 mln KZT", search_mode=SEARCH_MODE_HYBRID)
    if len(suggestions) < max_items:
        add("Search by document type", "Example: act or appendix for a contract.", q="appendix act contract", search_mode=SEARCH_MODE_HYBRID)

    return suggestions[:max_items]


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
    for key in ("document_type", "counterparty", "subject", "document_number", "document_date", "bin_iin", "contract_reference"):
        if search_query.entities.get(key):
            entity_values.append(str(search_query.entities[key]))
    if search_query.entities.get("amount", {}).get("raw"):
        entity_values.append(str(search_query.entities["amount"]["raw"]))
    for values in search_query.aliases.values():
        entity_values.extend(str(value) for value in values if value)
    for key in ("goods", "services", "works", "organization_name"):
        values = search_query.entities.get(key) or []
        if isinstance(values, str):
            entity_values.append(values)
        else:
            entity_values.extend(str(value) for value in values if value)

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
    for key in ("document_type", "counterparty", "subject", "document_number", "document_date", "bin_iin", "contract_reference"):
        value = query_entities.get(key)
        if value and str(value) in normalize_search_text(str(document_entities.get(key, ""))):
            matched.append(f"{key}: {value}")
    for key in ("goods", "services", "works", "organization_name"):
        query_values = query_entities.get(key) or []
        if isinstance(query_values, str):
            query_values = [query_values]
        document_values = document_entities.get(key) or []
        if isinstance(document_values, str):
            document_values = [document_values]
        document_text = normalize_search_text(" ".join(str(value) for value in document_values))
        for value in query_values:
            if value and str(value) in document_text:
                matched.append(f"{key}: {value}")
                break

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
        .filter(Q(from_document=document) | Q(to_document=document), is_confirmed=True)
        .select_related("from_document", "to_document")
        .order_by("-confidence", "-created_at")[:20]
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
                "confidence": relation.confidence,
                "source": relation.source,
            }
        )
        if len(related) >= limit:
            break
    return related


def accessible_similar_documents_for_search(
    document: Document,
    allowed_documents: QuerySet,
    *,
    limit: int = 2,
) -> list[Document]:
    queryset = allowed_documents.exclude(id=document.id)
    similarity_filter = Q()

    entities = document.search_entities or {}
    counterparty = entities.get("counterparty")
    if counterparty:
        similarity_filter |= Q(search_entities__counterparty__icontains=str(counterparty))
    document_type = entities.get("document_type")
    if document_type:
        similarity_filter |= Q(search_entities__document_type__icontains=str(document_type))
    if document.doc_type_id:
        similarity_filter |= Q(doc_type_id=document.doc_type_id)

    phrases = entities.get("key_phrases") or []
    for phrase in phrases[:3]:
        if phrase:
            similarity_filter |= Q(search_text_normalized__icontains=str(phrase))

    if not similarity_filter:
        return []

    return list(
        queryset.filter(similarity_filter)
        .distinct()
        .order_by("-doc_date", "-created_at")[:limit]
    )


def _document_index_states(document: Document) -> list[DocumentSearchIndexState]:
    try:
        states = list(document.search_index_states.all())
    except Exception:
        return []
    return sorted(states, key=lambda state: state.updated_at, reverse=True)


def _query_params_with_updates(current_params, **updates) -> dict:
    if hasattr(current_params, "lists"):
        params = {key: values[-1] for key, values in current_params.lists() if values and values[-1] not in (None, "")}
    else:
        params = {key: value for key, value in dict(current_params or {}).items() if value not in (None, "")}
    for key, value in updates.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = str(value)
    return params


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
