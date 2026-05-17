from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable

from dms.services.text_normalization import normalize_legal_form, normalize_value


ENTITY_TYPES = {
    "document_type",
    "counterparty",
    "organization_name",
    "legal_form",
    "bin_iin",
    "amount",
    "currency",
    "document_number",
    "document_date",
    "contract_reference",
    "subject",
    "goods",
    "services",
    "works",
    "person",
    "position",
    "department",
    "related_document_hint",
    "table_item",
    "search_phrase",
}

LEGAL_FORMS = {
    "ip": {"ip", "individual entrepreneur"},
    "too": {"too", "llp", "тоо"},
    "ooo": {"ooo", "ооо"},
    "ao": {"ao", "jsc", "ао"},
}

DOCUMENT_TYPE_ALIASES = {
    "contract": {"contract", "agreement", "договор", "контракт"},
    "invoice": {"invoice", "счет", "счёт", "инвойс"},
    "act": {"act", "акт"},
    "order": {"order", "приказ"},
    "appendix": {"appendix", "приложение", "specification", "спецификация"},
    "policy": {"policy", "regulation", "положение", "регламент"},
}

STOPWORDS = {
    "and", "or", "the", "with", "from", "for", "by", "of", "to",
    "и", "или", "с", "со", "от", "для", "на", "по", "об", "о", "к",
    "найти", "поиск", "документ", "документы",
}


@dataclass(frozen=True)
class ExtractedEntity:
    type: str
    value: str
    normalized: str
    confidence: float
    raw: str = ""
    source: str = "regex"
    metadata: dict | None = None

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["raw_value"] = payload["raw"] or payload["value"]
        payload["normalized_value"] = payload["normalized"]
        if not payload["metadata"]:
            payload.pop("metadata")
        return payload


def normalize_entity_text(value: str) -> str:
    return normalize_value(value)


def tokenize_entity_text(value: str) -> list[str]:
    tokens = []
    for token in normalize_entity_text(value).replace(",", " ").split():
        token = token.strip(".-/")
        if len(token) < 2 or token in STOPWORDS:
            continue
        tokens.append(token)
    return list(dict.fromkeys(tokens))


def extract_entities_from_text(
    text: str,
    *,
    doc_type_name: str = "",
    author: str = "",
    table_rows: Iterable[dict] | None = None,
) -> dict:
    normalized = normalize_entity_text(" ".join([text or "", doc_type_name or "", author or ""]))
    entities: list[ExtractedEntity] = []
    entities.extend(_extract_document_type(normalized))
    entities.extend(_extract_legal_forms(normalized))
    entities.extend(_extract_bin_iin(normalized))
    entities.extend(_extract_amounts(normalized))
    entities.extend(_extract_dates(normalized))
    entities.extend(_extract_document_numbers(normalized))
    entities.extend(_extract_contract_references(normalized))
    entities.extend(_extract_counterparties(normalized))
    entities.extend(_extract_subjects(normalized))
    entities.extend(_extract_goods_services_works(normalized))
    entities.extend(_extract_people_positions_departments(normalized))
    entities.extend(_extract_table_items(table_rows or []))
    entities.extend(_extract_table_items_from_text(text or ""))
    entities.extend(_extract_search_phrases(normalized))

    return build_entity_payload(entities, normalized)


def extract_query_entities(query: str) -> dict:
    return extract_entities_from_text(query)


def extract_entities(
    text: str,
    *,
    doc_type_name: str = "",
    author: str = "",
    table_rows: Iterable[dict] | None = None,
) -> dict:
    return extract_entities_from_text(
        text,
        doc_type_name=doc_type_name,
        author=author,
        table_rows=table_rows,
    )


def build_entity_payload(entities: list[ExtractedEntity], normalized_text: str) -> dict:
    deduped = _dedupe_entities(entities)
    by_type: dict[str, list[dict]] = {}
    for entity in deduped:
        by_type.setdefault(entity.type, []).append(entity.to_dict())

    primary = {key: values[0] for key, values in by_type.items() if values}
    key_phrases = tokenize_entity_text(normalized_text)[:24]

    payload = {
        "entities_by_type": by_type,
        "entity_confidence": {
            entity_type: round(sum(item["confidence"] for item in values) / len(values), 4)
            for entity_type, values in by_type.items()
            if values
        },
        "key_phrases": key_phrases,
    }

    if primary.get("document_type"):
        payload["document_type"] = primary["document_type"]["normalized"]
    if primary.get("counterparty"):
        payload["counterparty"] = primary["counterparty"]["normalized"]
    if primary.get("subject"):
        payload["subject"] = primary["subject"]["normalized"]
    if primary.get("amount"):
        amount_item = primary["amount"]
        payload["amount"] = {
            "value": amount_item.get("metadata", {}).get("value"),
            "raw": amount_item["raw"] or amount_item["value"],
            "currency": _primary_value(primary.get("currency"), default=amount_item.get("metadata", {}).get("currency", "")),
            "confidence": amount_item["confidence"],
        }
    if primary.get("document_number"):
        payload["document_number"] = primary["document_number"]["normalized"]
    if primary.get("document_date"):
        payload["document_date"] = primary["document_date"]["normalized"]
    if primary.get("bin_iin"):
        payload["bin_iin"] = primary["bin_iin"]["normalized"]
    if primary.get("contract_reference"):
        payload["contract_reference"] = primary["contract_reference"]["normalized"]
    for entity_type in ("goods", "services", "works", "legal_form", "organization_name", "currency"):
        values = [item["normalized"] for item in by_type.get(entity_type, []) if item.get("normalized")]
        if values:
            payload[entity_type] = list(dict.fromkeys(values))
    table_items = [item for item in by_type.get("table_item", []) if item.get("normalized")]
    if table_items:
        payload["table_items"] = table_items[:20]

    payload["overall_confidence"] = _overall_confidence(deduped)
    return {key: value for key, value in payload.items() if value not in ("", {}, [], None)}


def _extract_document_type(normalized: str) -> list[ExtractedEntity]:
    found = []
    for canonical, aliases in DOCUMENT_TYPE_ALIASES.items():
        if any(re.search(rf"\b{re.escape(alias)}\b", normalized) for alias in aliases):
            found.append(_entity("document_type", canonical, confidence=0.92, raw=canonical))
            break
    return found


def _extract_legal_forms(normalized: str) -> list[ExtractedEntity]:
    found = []
    for token in normalized.split():
        legal_form = normalize_legal_form(token)
        if legal_form:
            found.append(
                _entity(
                    "legal_form",
                    legal_form.normalized_value,
                    confidence=legal_form.confidence,
                    raw=legal_form.raw_value,
                    metadata={"variants": legal_form.variants[:12]},
                )
            )
    return found


def _extract_bin_iin(normalized: str) -> list[ExtractedEntity]:
    found = []
    for match in re.finditer(r"\b(?:bin|iin|бин|иин)\s*[:№#-]?\s*(\d{12})\b", normalized):
        found.append(_entity("bin_iin", match.group(1), confidence=0.96, raw=match.group(0)))
    return found


def _extract_amounts(normalized: str) -> list[ExtractedEntity]:
    found = []
    pattern = (
        r"(?<!\d)(\d+(?:[ ,.]\d{3})*(?:[,.]\d+)?)\s*"
        r"(млн|миллион|миллиона|миллионов|mln|million|тыс|тысяч|thousand|kzt|тенге|тг|₸|usd|eur|доллар(?:ов)?|евро)?\b"
    )
    for match in re.finditer(pattern, normalized):
        unit = match.group(2) or ""
        compact_number = match.group(1).replace(" ", "").replace(",", "").replace(".", "")
        prefix = normalized[max(0, match.start() - 12):match.start()]
        if re.search(r"\b(?:bin|iin|бин|иин)\s*$", prefix):
            continue
        if not unit and (len(compact_number) < 5 or re.fullmatch(r"20\d{2}", compact_number)):
            continue
        trailing_currency = re.match(r"\s*(kzt|тенге|тг|₸|usd|eur|доллар(?:ов)?|евро)\b", normalized[match.end():match.end() + 16])
        trailing_unit = trailing_currency.group(1) if trailing_currency else ""
        value = _parse_amount_value(match.group(1), unit)
        currency = _currency_for_unit(unit) or _currency_for_unit(trailing_unit)
        raw = match.group(0) + (f" {trailing_unit}" if trailing_unit else "")
        found.append(
            _entity(
                "amount",
                str(value),
                confidence=0.88 if unit else 0.68,
                raw=raw,
                metadata={"value": value, "currency": currency},
            )
        )
        if currency:
            found.append(_entity("currency", currency, confidence=0.9, raw=trailing_unit or unit))
    return found[:6]


def _extract_dates(normalized: str) -> list[ExtractedEntity]:
    found = []
    for match in re.finditer(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b", normalized):
        day, month, year = (int(part) for part in match.groups())
        iso_value = _safe_iso_date(year, month, day)
        if iso_value:
            found.append(_entity("document_date", iso_value, confidence=0.9, raw=match.group(0)))
    for match in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", normalized):
        year, month, day = (int(part) for part in match.groups())
        iso_value = _safe_iso_date(year, month, day)
        if iso_value:
            found.append(_entity("document_date", iso_value, confidence=0.92, raw=match.group(0)))
    return found[:4]


def _extract_document_numbers(normalized: str) -> list[ExtractedEntity]:
    found = []
    patterns = [
        r"\b(?:contract|agreement|договор|контракт|invoice|счет|счёт|акт)\s*(?:no|№|#|номер|n)?\s*[:№#-]?\s*([a-zа-я0-9/-]{2,40})",
        r"\b(?:no|№|#|номер)\s*([a-zа-я0-9/-]{2,40})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            value = match.group(1).strip(" .")
            if not value or value in STOPWORDS:
                continue
            found.append(_entity("document_number", value, confidence=0.82, raw=match.group(0)))
    return found[:4]


def _extract_contract_references(normalized: str) -> list[ExtractedEntity]:
    found = []
    for match in re.finditer(r"\b(?:к|по|under|for)\s+(?:договору|contract|agreement)\s*(?:№|#|no)?\s*([a-zа-я0-9/-]{2,40})", normalized):
        found.append(_entity("contract_reference", match.group(1), confidence=0.84, raw=match.group(0)))
        found.append(_entity("related_document_hint", match.group(0), confidence=0.72, raw=match.group(0)))
    return found[:4]


def _extract_counterparties(normalized: str) -> list[ExtractedEntity]:
    found = []
    patterns = [
        r"\b(?:контрагент|поставщик|supplier|counterparty|vendor)\s*[:\-]?\s+((?:ип|тоо|too|t00|t0o|llp|ооо|ao|ао|ip)?\s*[a-zа-я0-9][a-zа-я0-9 .'-]{2,100})",
        r"\b(?:с|with|от|from)\s+((?:ип|тоо|too|t00|t0o|llp|ооо|ao|ао|ip)\s+[a-zа-я0-9][a-zа-я0-9 .'-]{2,100})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            value = _trim_business_value(match.group(1))
            if value:
                value = _normalize_counterparty_legal_form(value)
                found.append(_entity("counterparty", value, confidence=0.86, raw=match.group(0)))
                org_name = _strip_legal_form(value)
                if org_name != value:
                    found.append(_entity("organization_name", org_name, confidence=0.78, raw=value))
    return found[:5]


def _extract_subjects(normalized: str) -> list[ExtractedEntity]:
    found = []
    patterns = [
        r"\b(?:subject|предмет)\s*[:\-]?\s+([a-zа-я0-9][a-zа-я0-9 .,'/-]{4,140})",
        r"\b(?:на|по|for)\s+([a-zа-я0-9][a-zа-я0-9 .,'/-]{4,140})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            value = _trim_business_value(match.group(1))
            if value:
                found.append(_entity("subject", value, confidence=0.72, raw=match.group(0)))
    return found[:4]


def _extract_goods_services_works(normalized: str) -> list[ExtractedEntity]:
    found = []
    patterns = {
        "goods": r"\b(?:goods|товары|инструменты|оборудование|materials)\b(?:\s*[:\-]?\s*([a-zа-я0-9 .,/-]{3,120}))?",
        "services": r"\b(?:services|услуги|сервис|обслуживание|subscription)\b(?:\s*[:\-]?\s*([a-zа-я0-9 .,/-]{3,120}))?",
        "works": r"\b(?:works|работы|монтаж|installation|implementation)\b(?:\s*[:\-]?\s*([a-zа-я0-9 .,/-]{3,120}))?",
    }
    for entity_type, pattern in patterns.items():
        for match in re.finditer(pattern, normalized):
            value = _trim_business_value(match.group(1) or match.group(0))
            found.append(_entity(entity_type, value, confidence=0.68, raw=match.group(0)))
    return found[:8]


def _extract_people_positions_departments(normalized: str) -> list[ExtractedEntity]:
    found = []
    for match in re.finditer(r"\b(?:person|ответственный|исполнитель)\s*[:\-]?\s+([a-zа-я .'-]{3,80})", normalized):
        found.append(_entity("person", _trim_business_value(match.group(1)), confidence=0.68, raw=match.group(0)))
    for match in re.finditer(r"\b(?:position|должность)\s*[:\-]?\s+([a-zа-я .'-]{3,80})", normalized):
        found.append(_entity("position", _trim_business_value(match.group(1)), confidence=0.68, raw=match.group(0)))
    for match in re.finditer(r"\b(?:department|департамент|отдел)\s*[:\-]?\s+([a-zа-я .'-]{3,80})", normalized):
        found.append(_entity("department", _trim_business_value(match.group(1)), confidence=0.7, raw=match.group(0)))
    return found[:6]


def _extract_table_items(table_rows: Iterable[dict]) -> list[ExtractedEntity]:
    found = []
    for row_index, row in enumerate(table_rows, start=1):
        if not isinstance(row, dict):
            continue
        text = normalize_entity_text(" ".join(str(value) for value in row.values() if value))
        if not text:
            continue
        found.append(
            _entity(
                "table_item",
                text[:180],
                confidence=0.55,
                raw=text[:180],
                source="table",
                metadata={"row_index": row_index},
            )
        )
    return found[:20]


def _extract_table_items_from_text(text: str) -> list[ExtractedEntity]:
    found = []
    for row_index, raw_line in enumerate((text or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if "|" in line:
            cells = [cell.strip() for cell in line.split("|") if cell.strip()]
        elif "\t" in line:
            cells = [cell.strip() for cell in line.split("\t") if cell.strip()]
        elif ";" in line and len(line.split(";")) >= 3:
            cells = [cell.strip() for cell in line.split(";") if cell.strip()]
        else:
            continue
        normalized_cells = [normalize_entity_text(cell) for cell in cells if normalize_entity_text(cell)]
        if len(normalized_cells) < 2:
            continue
        found.append(
            _entity(
                "table_item",
                " | ".join(normalized_cells)[:180],
                confidence=0.55,
                raw=line[:180],
                source="table_text",
                metadata={"row_index": row_index, "columns": len(normalized_cells)},
            )
        )
    return found[:20]


def _extract_search_phrases(normalized: str) -> list[ExtractedEntity]:
    tokens = tokenize_entity_text(normalized)
    phrases = []
    for index in range(0, max(len(tokens) - 1, 0)):
        phrase = " ".join(tokens[index:index + 3])
        if len(phrase) >= 8:
            phrases.append(_entity("search_phrase", phrase, confidence=0.48, raw=phrase, source="tokens"))
    return phrases[:12]


def _entity(entity_type: str, value: str, *, confidence: float, raw: str = "", source: str = "regex", metadata: dict | None = None) -> ExtractedEntity:
    value = str(value or "").strip(" .,:;-")
    return ExtractedEntity(
        type=entity_type,
        value=value,
        normalized=normalize_entity_text(value),
        confidence=round(max(0.0, min(confidence, 1.0)), 4),
        raw=raw or value,
        source=source,
        metadata=metadata or None,
    )


def _dedupe_entities(entities: list[ExtractedEntity]) -> list[ExtractedEntity]:
    best: dict[tuple[str, str], ExtractedEntity] = {}
    for entity in entities:
        if entity.type not in ENTITY_TYPES or not entity.normalized:
            continue
        key = (entity.type, entity.normalized)
        if key not in best or entity.confidence > best[key].confidence:
            best[key] = entity
    return sorted(best.values(), key=lambda item: (item.type, -item.confidence, item.normalized))


def _parse_amount_value(raw_value: str, unit: str) -> int:
    cleaned = raw_value.replace(" ", "").replace(",", ".")
    if cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        value = Decimal("0")
    multiplier = Decimal("1")
    if unit in {"млн", "миллион", "миллиона", "миллионов", "mln", "million"}:
        multiplier = Decimal("1000000")
    elif unit in {"тыс", "тысяч", "thousand"}:
        multiplier = Decimal("1000")
    return int(value * multiplier)


def _currency_for_unit(unit: str) -> str:
    if unit in {"kzt", "тенге", "тг", "₸"}:
        return "KZT"
    if unit in {"usd", "доллар", "долларов"}:
        return "USD"
    if unit in {"eur", "евро"}:
        return "EUR"
    return ""


def _safe_iso_date(year: int, month: int, day: int) -> str:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _trim_business_value(value: str) -> str:
    value = normalize_entity_text(value)
    value = re.split(
        r"\b(?:на сумму|сумма|стоимость|дата|номер|предмет|на|по|for|subject|amount|total|date|number|no|№|#|bin|iin|бин|иин|under|по договору)\b|\b\d+\s*(?:млн|тыс|kzt|usd|eur|тенге|тг|₸)\b",
        value,
    )[0]
    return value.strip(" .,:;-")[:160]


def _strip_legal_form(value: str) -> str:
    parts = value.split(maxsplit=1)
    if parts and normalize_legal_form(parts[0]):
        return parts[1].strip() if len(parts) > 1 else ""
    return re.sub(r"^(ип|тоо|too|t00|t0o|llp|ооо|ao|ао|ip)\s+", "", value).strip()


def _normalize_counterparty_legal_form(value: str) -> str:
    parts = value.split(maxsplit=1)
    if not parts:
        return value
    if not re.search(r"\d", parts[0]):
        return value
    legal_form = normalize_legal_form(parts[0])
    if not legal_form:
        return value
    if len(parts) == 1:
        return legal_form.normalized_value
    return f"{legal_form.normalized_value} {parts[1].strip()}"


def _primary_value(item: dict | None, *, default: str = "") -> str:
    if not item:
        return default
    return item.get("value") or item.get("normalized") or default


def _overall_confidence(entities: list[ExtractedEntity]) -> float:
    signal_entities = [entity.confidence for entity in entities if entity.type != "search_phrase"]
    if not signal_entities:
        return 0.0
    return round(sum(signal_entities) / len(signal_entities), 4)
