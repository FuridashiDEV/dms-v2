import json
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import date
from typing import List, Optional, Set

import ollama


# ======================================================
# HELPERS
# ======================================================

def _clean(value: Optional[str]) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _looks_like_raw_sentence_title(title: str) -> bool:
    normalized = _compact_text(title)
    if not normalized:
        return True

    lowered = normalized.lower()
    words = lowered.split()

    if len(words) >= 8:
        return True

    if lowered.startswith(("я ", "мы ", "мне ", "меня ", "хочу ", "считаю ", "потому что ")):
        return True

    if any(mark in lowered for mark in ["потому что", "для меня"]) or any(mark in normalized for mark in ["?", "!"]):
        return True

    return False


def _extract_named_entity_after_preposition(text: str, preposition: str) -> str:
    pattern = rf"(?:^|[\s\"'«»]){preposition}\s+([A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9 .&\\-]{{2,80}})"
    match = re.search(pattern, text)
    if not match:
        return ""
    value = match.group(1).strip(" .,!?:;\"'«»")
    value = re.split(r"\s+(?:потому|так как|где|котор|для)\b", value, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    return value[:80]


def _infer_title_from_text(text: str, fallback_doc_type: Optional[str] = None) -> str:
    normalized = _compact_text(text)
    if not normalized:
        return ""

    lowered = normalized.lower()
    institution = (
        _extract_named_entity_after_preposition(normalized, "в")
        or _extract_named_entity_after_preposition(normalized, "во")
    )

    if "поступить" in lowered or "поступление" in lowered:
        if institution:
            return f"Мотивационное письмо для поступления в {institution}"[:180]
        return "Мотивационное письмо для поступления"

    if any(token in lowered for token in ["мотивационное письмо", "эссе", "application essay"]):
        if institution:
            return f"Мотивационное письмо для {institution}"[:180]
        return "Мотивационное письмо"

    if fallback_doc_type:
        topic_match = re.search(r"(?:о|об)\s+([A-Za-zА-Яа-яЁё0-9][^.!?\n]{4,120})", normalized, re.IGNORECASE)
        if topic_match:
            topic = topic_match.group(1).strip(" ,;:.")
            return f"{fallback_doc_type} о {topic}"[:180]
        return fallback_doc_type[:180]

    lines = [
        _compact_text(line.strip(" -:;,."))
        for line in text.splitlines()
        if _compact_text(line)
    ]
    meaningful = [line for line in lines if len(line) >= 12 and not _looks_like_raw_sentence_title(line)]
    if meaningful:
        return meaningful[0][:180]

    return normalized[:180]


def _finalize_title(title_ru: str, text: str, fallback_doc_type: Optional[str] = None) -> str:
    normalized = _compact_text(title_ru)
    if normalized and not _looks_like_raw_sentence_title(normalized):
        return normalized[:180]

    inferred = _infer_title_from_text(text, fallback_doc_type=fallback_doc_type)
    if inferred:
        return inferred[:180]

    return normalized[:180]


def _normalize_doc_type(
    ai_type: Optional[str],
    allowed_types: Set[str],
) -> Optional[str]:
    if not ai_type or not allowed_types:
        return None

    ai_norm = ai_type.strip().lower()

    for real in allowed_types:
        real_norm = real.lower()
        if ai_norm in real_norm or real_norm in ai_norm:
            return real

    return None


def _translate_ru_to_kk(text_ru: str) -> str:
    """
    Строгий перевод RU → KZ.
    Без комментариев. Без пояснений. Без служебного текста.
    """
    text_ru = text_ru.strip()
    if not text_ru:
        return ""

    prompt = f"""
Ты выполняешь ТОЛЬКО перевод текста.

СТРОГИЕ ПРАВИЛА:
- Верни ТОЛЬКО перевод
- НЕ добавляй комментарии
- НЕ добавляй пояснения
- НЕ добавляй служебный текст
- НЕ повторяй исходный текст
- БЕЗ кавычек
- БЕЗ точек вне предложения

Переведи с русского языка на казахский язык
в официально-деловом стиле.

ТЕКСТ:
{text_ru}
"""

    try:
        result = ollama.chat(
            model="mistral",
            messages=[{"role": "user", "content": prompt}],
        )
        return _clean(result.get("message", {}).get("content"))
    except Exception:
        return ""



# ======================================================
# MAIN PARSER
# ======================================================

import json
from datetime import date, datetime
from typing import List, Optional, Set

import ollama

from dms.services.document_metadata import extract_doc_type


def parse_document(
    *,
    text: str,
    candidate_dates: List[date],
    allowed_doc_types: Optional[Set[str]] = None,
) -> dict:

    if not isinstance(candidate_dates, list):
        raise TypeError("candidate_dates must be list[date]")

    date_strings = [
        d.strftime("%d.%m.%Y")
        for d in candidate_dates
        if isinstance(d, date)
    ]

    prompt = f"""
Ты — архивный модуль системы электронного документооборота университета.

Твоя задача:
1) Сформировать официальное архивное название документа.
2) Сформировать краткое официальное описание (1–3 предложения).
3) Если в тексте явно указан тип документа — определить его.
4) Если в тексте есть дата — выбрать её индекс из списка.
5) Если в тексте явно указан автор или подписант — вернуть его.
6) Определить язык документа: RU, KK, EN, MIXED или UNKNOWN.
7) Предложить категорию хранения, если она читается из содержания.
8) Определить признаки юридического удержания: true или false.

ВАЖНО:
- Название и описание вернуть ТОЛЬКО на русском языке.
- Даже если документ на казахском — смысл передай на русском.
- Ничего не придумывать.
- Никаких комментариев.
- Ответ СТРОГО в формате JSON.
- Без текста вне JSON.

ФОРМАТ:
{{
  "title_ru": "",
  "summary_ru": "",
  "doc_type": null,
  "date_index": null,
  "document_author": "",
  "language": "UNKNOWN",
  "retention_category": "",
  "legal_hold": false
}}

ДОСТУПНЫЕ ДАТЫ:
{list(enumerate(date_strings))}

ТЕКСТ ДОКУМЕНТА:
{text[:4000]}
"""

    def build_fallback() -> dict:
        fallback_doc_type = _normalize_doc_type(
            extract_doc_type(text),
            allowed_doc_types or set(),
        )
        header_lines = [
            line.strip(" -:;,.")
            for line in text.splitlines()[:12]
            if line.strip()
        ]
        title = _infer_title_from_text("\n".join(header_lines) or text, fallback_doc_type=fallback_doc_type)
        if not title:
            compact = _compact_text(text)
            title = compact[:180].strip()

        compact = _compact_text(text)
        summary = compact[:320].strip()
        if len(compact) > 320:
            summary = summary.rstrip(" ,;:") + "..."

        fallback_idx = 0 if candidate_dates else None

        return {
            "title_ru": title,
            "summary_ru": summary,
            "doc_type": fallback_doc_type,
            "date_index": fallback_idx,
            "document_author": "",
            "language": "UNKNOWN",
            "retention_category": "",
            "legal_hold": False,
        }

    def _call_model() -> str:
        result = ollama.chat(
            model="mistral",
            messages=[{"role": "user", "content": prompt}],
        )
        return result.get("message", {}).get("content", "")

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_call_model)
    try:
        raw = future.result(timeout=8)
    except (FuturesTimeoutError, Exception):
        raw = ""
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    try:
        data = json.loads(raw)
    except Exception:
        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            try:
                data = json.loads(match.group(0))
            except Exception:
                data = {}
        else:
            data = {}

    fallback = build_fallback()
    title_ru = _finalize_title(
        (data.get("title_ru") or "").strip(),
        text,
        fallback_doc_type=fallback.get("doc_type"),
    )
    summary_ru = (data.get("summary_ru") or "").strip()

    # Если модель ничего осмысленного не вернула
    if not title_ru and not summary_ru:
        return fallback

    # -----------------------------
    # DATE INDEX
    # -----------------------------
    idx = data.get("date_index")

    if isinstance(idx, int) and 0 <= idx < len(candidate_dates):
        pass
    elif isinstance(idx, str):
        try:
            parsed = datetime.strptime(idx, "%d.%m.%Y").date()
            if parsed in candidate_dates:
                idx = candidate_dates.index(parsed)
            else:
                idx = None
        except Exception:
            idx = None
    else:
        idx = None

    # -----------------------------
    # DOC TYPE
    # -----------------------------
    doc_type = _normalize_doc_type(
        data.get("doc_type"),
        allowed_doc_types or set(),
    ) or fallback.get("doc_type")

    language = data.get("language")
    if language not in {"RU", "KK", "EN", "MIXED", "UNKNOWN"}:
        language = "UNKNOWN"

    document_author = _clean(data.get("document_author"))
    retention_category = _clean(data.get("retention_category"))
    legal_hold = data.get("legal_hold")
    if not isinstance(legal_hold, bool):
        legal_hold = False

    return {
        "title_ru": title_ru,
        "summary_ru": summary_ru,
        "doc_type": doc_type,
        "date_index": idx,
        "document_author": document_author,
        "language": language,
        "retention_category": retention_category,
        "legal_hold": legal_hold,
    }
