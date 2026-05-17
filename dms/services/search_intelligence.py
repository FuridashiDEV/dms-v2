from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from django.conf import settings

from dms.services.entity_extraction import extract_entities as extract_structured_entities


DOCUMENT_TYPE_ALIASES = {
    "contract": {"договор", "контракт", "agreement", "contract"},
    "invoice": {"счет", "счёт", "invoice", "инвойс"},
    "act": {"акт", "act"},
    "order": {"приказ", "order"},
    "appendix": {"приложение", "appendix", "спецификация"},
    "policy": {"положение", "регламент", "policy"},
}

DEFAULT_ALIASES = {
    "invision": {"инвижн", "инвижен", "in vision", "invision"},
    "инвижн": {"invision", "in vision", "инвижн", "инвижен"},
    "ип": {"индивидуальный предприниматель", "ip", "ип"},
    "too": {"тоо", "llp", "тoo"},
    "тоо": {"too", "llp", "тоо"},
    "llp": {"тоо", "too", "llp"},
}

STOPWORDS = {
    "для",
    "или",
    "это",
    "как",
    "что",
    "при",
    "the",
    "and",
    "with",
    "from",
    "документ",
    "документы",
    "найти",
    "поиск",
    "на",
    "с",
    "по",
    "об",
    "о",
}


@dataclass(frozen=True)
class SearchQuery:
    raw: str
    normalized: str
    expanded_text: str
    tokens: list[str]
    aliases: dict[str, list[str]] = field(default_factory=dict)
    entities: dict = field(default_factory=dict)


def normalize_search_text(value: str) -> str:
    text = (value or "").lower().replace("ё", "е")
    text = re.sub(r"[«»\"'“”]", " ", text)
    text = re.sub(r"[^0-9a-zа-яәғқңөұүһі\s.,-]+", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(value: str) -> list[str]:
    tokens = []
    for token in normalize_search_text(value).replace(",", " ").split():
        token = token.strip(".-")
        if len(token) < 2 or token in STOPWORDS:
            continue
        tokens.append(token)
    return list(dict.fromkeys(tokens))


def alias_dictionary() -> dict[str, set[str]]:
    aliases = {key: set(values) for key, values in DEFAULT_ALIASES.items()}
    for key, values in getattr(settings, "SEARCH_ALIASES", {}).items():
        normalized_key = normalize_search_text(key)
        if normalized_key:
            aliases.setdefault(normalized_key, set()).update(normalize_search_text(value) for value in values)
    return aliases


def expand_aliases(tokens: Iterable[str]) -> dict[str, list[str]]:
    aliases = alias_dictionary()
    expanded = {}
    for token in tokens:
        variants = set()
        for alias_key, alias_values in aliases.items():
            if token == alias_key or token in alias_values:
                variants.add(alias_key)
                variants.update(alias_values)
        if variants:
            expanded[token] = sorted(item for item in variants if item)
    return expanded


def _detect_document_type(normalized: str) -> str:
    for canonical, values in DOCUMENT_TYPE_ALIASES.items():
        if any(re.search(rf"\b{re.escape(value)}\b", normalized) for value in values):
            return canonical
    return ""


def _extract_amount(normalized: str) -> dict:
    match = re.search(
        r"(?<!\d)(\d+(?:[,.]\d+)?)\s*"
        r"(млн|миллион|миллиона|миллионов|тыс|тысяч|kzt|тг|тенге|₸)\b",
        normalized,
    )
    if not match:
        return {}
    value = Decimal(match.group(1).replace(",", "."))
    unit = match.group(2) or ""
    multiplier = Decimal("1")
    if unit in {"млн", "миллион", "миллиона", "миллионов"}:
        multiplier = Decimal("1000000")
    elif unit in {"тыс", "тысяч"}:
        multiplier = Decimal("1000")
    amount = value * multiplier
    return {
        "value": int(amount),
        "raw": match.group(0),
        "currency": "KZT" if unit in {"kzt", "тг", "тенге", "₸"} else "",
    }


def _extract_counterparty(normalized: str) -> str:
    patterns = [
        r"\b(?:с|от|для)\s+(ип|тоо|too|llp|ао|ооо)?\s*([a-zа-я0-9][a-zа-я0-9\s.-]{2,80})",
        r"\b(?:контрагент|поставщик)\s*[:\-]?\s+([a-zа-я0-9][a-zа-я0-9\s.-]{2,80})",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        value = " ".join(part for part in match.groups() if part).strip()
        value = re.split(
            r"\b(?:на|по|для|сумма|стоимость|предмет|назначение)\b",
            value,
        )[0].strip(" .-")
        if value:
            return value[:120]
    return ""


def _extract_subject(normalized: str) -> str:
    match = re.search(r"\b(?:на|по)\s+([a-zа-я0-9][a-zа-я0-9\s.-]{3,120})", normalized)
    if not match:
        return ""
    value = re.split(
        r"\b(?:на сумму|сумма|стоимость|за)\b|\bна\s+\d",
        match.group(1),
    )[0].strip(" .-")
    return value[:120]


def extract_entities_from_text(text: str, *, doc_type_name: str = "", author: str = "") -> dict:
    normalized = normalize_search_text(" ".join([text or "", doc_type_name or "", author or ""]))
    tokens = tokenize(normalized)
    entities = extract_structured_entities(text, doc_type_name=doc_type_name, author=author)
    if tokens and "key_phrases" not in entities:
        entities["key_phrases"] = tokens[:18]
    aliases = expand_aliases(tokens)
    if aliases:
        entities["aliases"] = aliases
    return {key: value for key, value in entities.items() if value not in ("", {}, [], None)}


def build_search_query(raw_query: str) -> SearchQuery:
    normalized = normalize_search_text(raw_query)
    tokens = tokenize(normalized)
    aliases = expand_aliases(tokens)
    expanded_terms = list(tokens)
    for values in aliases.values():
        expanded_terms.extend(values)
    entities = extract_entities_from_text(raw_query)
    expanded_text = " ".join(dict.fromkeys([normalized, *expanded_terms]))
    return SearchQuery(
        raw=raw_query or "",
        normalized=normalized,
        expanded_text=expanded_text,
        tokens=list(dict.fromkeys(expanded_terms)),
        aliases=aliases,
        entities=entities,
    )


def build_document_search_text(document) -> str:
    entities = document.search_entities or {}
    entity_parts = []
    for key in ("document_type", "counterparty", "subject", "document_number", "document_date", "bin_iin", "contract_reference"):
        if entities.get(key):
            entity_parts.append(str(entities[key]))
    if entities.get("amount", {}).get("raw"):
        entity_parts.append(str(entities["amount"]["raw"]))
    if entities.get("amount", {}).get("value"):
        entity_parts.append(str(entities["amount"]["value"]))
    for key in ("goods", "services", "works", "legal_form", "organization_name", "currency"):
        values = entities.get(key) or []
        if isinstance(values, str):
            entity_parts.append(values)
        else:
            entity_parts.extend(str(value) for value in values if value)
    for item in entities.get("table_items", []):
        if isinstance(item, dict):
            entity_parts.extend(str(item.get(key, "")) for key in ("value", "normalized", "raw") if item.get(key))
    for values in entities.get("entities_by_type", {}).values():
        for item in values:
            if isinstance(item, dict):
                entity_parts.extend(str(item.get(key, "")) for key in ("value", "normalized", "raw") if item.get(key))
    entity_parts.extend(entities.get("key_phrases", []))
    for values in entities.get("aliases", {}).values():
        entity_parts.extend(values)
    return normalize_search_text(
        " ".join(
            filter(
                None,
                [
                    document.title,
                    document.description,
                    document.document_author,
                    document.source_file_name,
                    document.doc_type.name if document.doc_type else "",
                    document.folder.name if document.folder else "",
                    document.extracted_text,
                    " ".join(entity_parts),
                ],
            )
        )
    )


def update_document_search_metadata(document) -> dict:
    text = " ".join(
        filter(
            None,
            [
                document.title,
                document.description,
                document.document_author,
                document.source_file_name,
                document.doc_type.name if document.doc_type else "",
                document.extracted_text,
            ],
        )
    )
    document.search_entities = extract_entities_from_text(
        text,
        doc_type_name=document.doc_type.name if document.doc_type else "",
        author=document.document_author,
    )
    document.search_text_normalized = build_document_search_text(document)
    return document.search_entities


def score_document_for_query(document, query: SearchQuery, semantic_score: float = 0.0) -> tuple[float, list[str]]:
    text = document.search_text_normalized or build_document_search_text(document)
    entities = document.search_entities or {}
    reasons = []

    token_hits = [token for token in query.tokens if token and token in text]
    lexical_score = min(1.0, len(token_hits) / max(len(query.tokens), 1))
    if token_hits:
        reasons.append("matched text/alias terms: " + ", ".join(token_hits[:5]))

    alias_hits = []
    for source, variants in query.aliases.items():
        if source in text or any(variant in text for variant in variants):
            alias_hits.append(source)
    if alias_hits:
        lexical_score = max(lexical_score, 0.8)
        reasons.append("alias matched: " + ", ".join(alias_hits[:3]))

    entity_score = 0.0
    query_entities = query.entities
    if query_entities.get("document_type") and query_entities.get("document_type") == entities.get("document_type"):
        entity_score += 0.22
        reasons.append(f"document type matched: {query_entities['document_type']}")
    if query_entities.get("counterparty") and query_entities["counterparty"] in text:
        entity_score += 0.28
        reasons.append(f"counterparty matched: {query_entities['counterparty']}")
    if query_entities.get("subject") and query_entities["subject"] in text:
        entity_score += 0.22
        reasons.append(f"subject matched: {query_entities['subject']}")
    document_amount = entities.get("amount") or {}
    if (
        query_entities.get("amount", {}).get("value")
        and (
            query_entities["amount"]["value"] == document_amount.get("value")
            or str(query_entities["amount"]["value"]) in text.replace(" ", "")
        )
    ):
        entity_score += 0.12
        reasons.append(f"amount matched: {query_entities['amount']['raw']}")

    for key, weight in (
        ("document_number", 0.16),
        ("document_date", 0.12),
        ("bin_iin", 0.18),
        ("contract_reference", 0.14),
    ):
        value = query_entities.get(key)
        if value and (str(value) in text or str(value) == str(entities.get(key, ""))):
            entity_score += weight
            reasons.append(f"{key} matched: {value}")

    for key, weight in (("goods", 0.08), ("services", 0.08), ("works", 0.08), ("organization_name", 0.1)):
        query_values = query_entities.get(key) or []
        if isinstance(query_values, str):
            query_values = [query_values]
        hits = [str(value) for value in query_values if value and str(value) in text]
        if hits:
            entity_score += weight
            reasons.append(f"{key} matched: {', '.join(hits[:2])}")

    if semantic_score:
        reasons.append(f"semantic score {semantic_score:.2f}")

    score = semantic_score * 0.35 + lexical_score * 0.32 + min(entity_score, 0.84)
    return round(score, 4), reasons[:6]


def chunk_text(text: str, *, chunk_size: int = 1200, overlap: int = 160) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        chunk = text[start:start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        start += max(chunk_size - overlap, 1)
    return chunks
