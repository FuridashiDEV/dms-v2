import re
from datetime import datetime, date
from typing import List, Optional


# =========================
# DATE PATTERNS (ПО ПРИОРИТЕТУ)
# =========================

DATE_PATTERNS = [
    # Приказы / распоряжения: самый высокий приоритет
    (r"№\s*\S+\s*от\s*(\d{2}\.\d{2}\.\d{4})", 0),

    # Формальный стиль: "30.10.2018 г."
    (r"(\d{2}\.\d{2}\.\d{4})\s*г\.", 1),

    # Любая дата
    (r"(\d{2}\.\d{2}\.\d{4})", 2),
]


# =========================
# DOC TYPE RULES
# =========================

DOC_TYPE_RULES = {
    "Приказ": ["ПРИКАЗ", "БҰЙЫРАМЫН"],
    "Распоряжение": ["РАСПОРЯЖЕНИЕ"],
    "Положение": ["ПОЛОЖЕНИЕ"],
    "Договор": ["ДОГОВОР", "AGREEMENT"],
    "Правила": ["ПРАВИЛА", "ҚАҒИДАЛАР"],
}


# =========================
# DATE EXTRACTION (КЛЮЧЕВОЕ)
# =========================

def extract_candidate_dates(text: str, *, max_lines: int = 40) -> List[date]:
    """
    Извлекает возможные даты документа из шапки
    с учётом приоритетов и позиции в тексте.

    Возвращает список datetime.date,
    отсортированный по вероятности (лучшая — первая).
    """
    if not text:
        return []

    lines = text.splitlines()[:max_lines]
    header = "\n".join(lines)

    collected: list[tuple[int, int, date]] = []
    seen: set[date] = set()

    for pattern, weight in DATE_PATTERNS:
        for match in re.finditer(pattern, header):
            raw = match.group(1)

            try:
                d = datetime.strptime(raw, "%d.%m.%Y").date()
            except ValueError:
                continue

            if d in seen:
                continue
            seen.add(d)

            # позиция в тексте (чем ближе к началу — тем важнее)
            position = match.start()

            collected.append((weight, position, d))

    # сортировка:
    # 1) по типу шаблона
    # 2) по позиции в документе
    collected.sort(key=lambda x: (x[0], x[1]))

    return [d for _, _, d in collected]


# =========================
# DOC TYPE EXTRACTION
# =========================

def extract_doc_type(text: str) -> Optional[str]:
    """
    Определяет тип документа по ключевым словам в шапке.
    Используется как вспомогательная эвристика.
    """
    if not text:
        return None

    header = "\n".join(text.splitlines()[:20]).upper()

    for doc_type, keywords in DOC_TYPE_RULES.items():
        for kw in keywords:
            if kw in header:
                return doc_type

    return None
