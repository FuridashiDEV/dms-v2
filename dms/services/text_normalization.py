from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Iterable


LOOKALIKE_LATIN_TO_CYRILLIC = str.maketrans(
    {
        "a": "а",
        "c": "с",
        "e": "е",
        "h": "н",
        "k": "к",
        "m": "м",
        "o": "о",
        "p": "р",
        "t": "т",
        "x": "х",
        "y": "у",
        "b": "в",
    }
)

LOOKALIKE_CYRILLIC_TO_LATIN = str.maketrans(
    {
        "а": "a",
        "с": "c",
        "е": "e",
        "н": "h",
        "к": "k",
        "м": "m",
        "о": "o",
        "р": "p",
        "т": "t",
        "х": "x",
        "у": "y",
        "в": "b",
    }
)

TRANSLIT_CYRILLIC_TO_LATIN = {
    "а": "a",
    "ә": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "ғ": "g",
    "д": "d",
    "е": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "і": "i",
    "й": "i",
    "к": "k",
    "қ": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "ң": "n",
    "о": "o",
    "ө": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ұ": "u",
    "ү": "u",
    "ф": "f",
    "х": "h",
    "һ": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sh",
    "ы": "y",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}

LEGAL_FORM_ALIASES = {
    "ip": {"ip", "iп", "іп", "ип", "и.п.", "individual entrepreneur"},
    "too": {"too", "tоо", "t00", "тоо", "тoo", "т0о", "т00", "llp"},
    "ooo": {"ooo", "0oo", "ооо", "oоо"},
    "ao": {"ao", "ао", "jsc"},
}

BUILTIN_SEARCH_ALIASES = {
    "invision": {"in vision", "инвижн", "инвижен", "инвишн", "іnvision"},
    "ip": {"ип", "іп", "individual entrepreneur"},
    "too": {"тоо", "тoo", "llp"},
    "llp": {"too", "тоо"},
    "contract": {"договор", "контракт", "келісім", "agreement"},
    "invoice": {"счет", "счёт", "инвойс", "шот"},
    "act": {"акт", "акт выполненных работ"},
}


@dataclass(frozen=True)
class NormalizedText:
    raw_value: str
    normalized_value: str
    tokens: list[str] = field(default_factory=list)
    variants: list[str] = field(default_factory=list)
    corrections: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedLegalForm:
    raw_value: str
    normalized_value: str
    variants: list[str]
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_value(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[«»\"'“”]", " ", text)
    text = re.sub(r"[‐‑‒–—−]", "-", text)
    text = re.sub(r"[^0-9a-zа-яәғқңөұүһі\s.,#№/_-]+", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def tokenize_normalized_text(value: str) -> list[str]:
    tokens = []
    for token in normalize_value(value).replace(",", " ").split():
        token = token.strip(".-/")
        if len(token) < 2:
            continue
        tokens.append(token)
    return list(dict.fromkeys(tokens))


def normalize_text(value: str) -> NormalizedText:
    normalized = normalize_value(value)
    tokens = tokenize_normalized_text(normalized)
    variants = expand_text_variants(normalized, tokens=tokens)
    corrections = []
    for token in tokens:
        corrected = conservative_ocr_variants(token)
        for variant in corrected:
            if variant != token:
                corrections.append({"raw_value": token, "normalized_value": variant, "source": "ocr_foundation"})
    return NormalizedText(
        raw_value=value or "",
        normalized_value=normalized,
        tokens=tokens,
        variants=variants,
        corrections=corrections,
    )


def expand_text_variants(value: str, *, tokens: Iterable[str] | None = None) -> list[str]:
    normalized = normalize_value(value)
    variants = {normalized}
    token_list = list(tokens or tokenize_normalized_text(normalized))
    if normalized:
        variants.add(normalized.translate(LOOKALIKE_LATIN_TO_CYRILLIC))
        variants.add(normalized.translate(LOOKALIKE_CYRILLIC_TO_LATIN))
        transliterated = transliterate_cyrillic_to_latin(normalized)
        if transliterated != normalized:
            variants.add(transliterated)
    for token in token_list:
        variants.update(conservative_ocr_variants(token))
        legal_form = normalize_legal_form(token)
        if legal_form:
            variants.add(legal_form.normalized_value)
            variants.update(legal_form.variants)
    return sorted(item for item in variants if item)


def normalize_legal_form(value: str) -> NormalizedLegalForm | None:
    raw = value or ""
    normalized = normalize_value(raw).replace(" ", "")
    if not normalized:
        return None
    candidates = {
        normalized,
        normalized.translate(LOOKALIKE_LATIN_TO_CYRILLIC),
        normalized.translate(LOOKALIKE_CYRILLIC_TO_LATIN),
        *conservative_ocr_variants(normalized),
    }
    for canonical, aliases in LEGAL_FORM_ALIASES.items():
        normalized_aliases = {normalize_value(alias).replace(" ", "") for alias in aliases}
        if candidates & normalized_aliases or normalized == canonical:
            variants = sorted(normalized_aliases | {canonical})
            confidence = 0.96 if normalized in normalized_aliases | {canonical} else 0.82
            return NormalizedLegalForm(
                raw_value=raw,
                normalized_value=canonical,
                variants=variants,
                confidence=confidence,
            )
    return None


def conservative_ocr_variants(token: str) -> set[str]:
    normalized = normalize_value(token).replace(" ", "")
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    variants = {normalized}
    if re.search(r"[a-zа-яәғқңөұүһі]", normalized, flags=re.IGNORECASE) and re.search(r"\d", normalized):
        variants.add(normalized.replace("0", "o"))
        variants.add(normalized.replace("0", "о"))
        variants.add(normalized.replace("1", "l"))
        variants.add(normalized.replace("5", "s"))
    if normalized in {"т00", "t00", "т0о", "t0o"}:
        variants.update({"too", "тоо"})
    return {variant for variant in variants if variant}


def transliterate_cyrillic_to_latin(value: str) -> str:
    result = []
    for char in normalize_value(value):
        result.append(TRANSLIT_CYRILLIC_TO_LATIN.get(char, char))
    return "".join(result)


def normalize_alias_map(alias_map: dict[str, Iterable[str]]) -> dict[str, set[str]]:
    normalized_aliases: dict[str, set[str]] = {}
    for raw_key, raw_values in alias_map.items():
        key_norm = normalize_value(raw_key)
        if not key_norm:
            continue
        variants = set(expand_text_variants(key_norm))
        for raw_value in raw_values:
            value_norm = normalize_value(raw_value)
            if not value_norm:
                continue
            variants.add(value_norm)
            variants.update(expand_text_variants(value_norm))
        normalized_aliases.setdefault(key_norm, set()).update(variants)
    return normalized_aliases


def expand_multilingual_query(query: str, alias_map: dict[str, Iterable[str]] | None = None) -> dict:
    normalized = normalize_text(query)
    aliases = normalize_alias_map(alias_map or BUILTIN_SEARCH_ALIASES)
    expanded_terms = set(normalized.tokens)
    matched_aliases: dict[str, list[str]] = {}
    query_for_phrase_match = f" {normalized.normalized_value} "
    for term in [normalized.normalized_value, *normalized.tokens, *normalized.variants]:
        if not term:
            continue
        for alias_key, alias_values in aliases.items():
            phrase_match = " " in alias_key and f" {alias_key} " in query_for_phrase_match
            if term == alias_key or term in alias_values or phrase_match:
                expanded_terms.add(alias_key)
                expanded_terms.update(alias_values)
                matched_aliases.setdefault(term, [])
                matched_aliases[term] = sorted(set(matched_aliases[term]) | alias_values | {alias_key})
    for variant in normalized.variants:
        expanded_terms.update(tokenize_normalized_text(variant))
    return {
        "raw_value": normalized.raw_value,
        "normalized_value": normalized.normalized_value,
        "tokens": normalized.tokens,
        "variants": normalized.variants,
        "expanded_terms": sorted(term for term in expanded_terms if term),
        "aliases": matched_aliases,
        "corrections": normalized.corrections,
    }
