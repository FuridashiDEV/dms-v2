import re
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from dms.models import Document


@dataclass
class RetentionSuggestion:
    category: str
    years: int | None
    reason: str
    suggested_until: str | None


def normalize_document_fingerprint(doc: Document) -> str:
    text = " ".join(
        part for part in [doc.title, doc.document_author, doc.doc_type.name if doc.doc_type_id else ""] if part
    ).lower()
    text = re.sub(r"\b(19|20)\d{2}\b", " ", text)
    text = re.sub(r"\b(v|версия|редакция|rev)\s*\d+\b", " ", text)
    text = re.sub(r"[^a-zа-яәіңғүұқөһ0-9]+", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def get_superseded_candidates(doc: Document, allowed_queryset, limit: int = 5):
    fingerprint = normalize_document_fingerprint(doc)
    if not fingerprint:
        return []

    candidates = []
    qs = (
        allowed_queryset.exclude(pk=doc.pk)
        .filter(department_id=doc.department_id)
        .select_related("doc_type", "department")
    )
    if doc.doc_type_id:
        qs = qs.filter(doc_type_id=doc.doc_type_id)

    for candidate in qs.order_by("-doc_date", "-created_at")[:50]:
        if normalize_document_fingerprint(candidate) != fingerprint:
            continue
        if doc.doc_date and candidate.doc_date and candidate.doc_date > doc.doc_date:
            continue
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return candidates


def build_relation_suggestions(doc: Document, allowed_queryset, limit: int = 4):
    suggestions = []
    for candidate in get_superseded_candidates(doc, allowed_queryset, limit=limit):
        relation_type = "REPLACES"
        label = "Вероятно заменяет"
        if doc.doc_date and candidate.doc_date and doc.doc_date == candidate.doc_date:
            relation_type = "RELATED_TO"
            label = "Вероятно связан с"
        suggestions.append(
            {
                "label": label,
                "relation_type": relation_type,
                "target": candidate,
            }
        )
    return suggestions


def build_retention_assistant(doc: Document) -> RetentionSuggestion | None:
    haystack = " ".join(
        part
        for part in [doc.title, doc.description, doc.document_author, doc.doc_type.name if doc.doc_type_id else ""]
        if part
    ).lower()

    rules = [
        ("Кадровый документ", 75, ["кадр", "труд", "сотрудник", "личн", "прием", "увольн"]),
        ("Договорной документ", 10, ["договор", "контракт", "соглашение", "допсоглашение"]),
        ("Финансовый документ", 5, ["бюджет", "смет", "финанс", "оплат", "счет", "акт"]),
        ("Учебно-методический документ", 5, ["учеб", "силлабус", "программа", "метод", "дисциплин"]),
        ("Распорядительный документ", 10, ["приказ", "распоряжение", "положение", "регламент"]),
    ]

    for category, years, keywords in rules:
        if any(keyword in haystack for keyword in keywords):
            base_date = doc.doc_date or timezone.localdate()
            suggested_until = base_date + timedelta(days=365 * years)
            return RetentionSuggestion(
                category=category,
                years=years,
                reason=f"Категория определена по содержанию и реквизитам: {', '.join(keywords[:3])}.",
                suggested_until=suggested_until.strftime("%d.%m.%Y"),
            )

    return RetentionSuggestion(
        category="Общий управленческий документ",
        years=5,
        reason="Точный тип хранения не определен, поэтому предложен базовый срок для внутреннего документа.",
        suggested_until=(timezone.localdate() + timedelta(days=365 * 5)).strftime("%d.%m.%Y"),
    )


def build_card_quality(doc: Document):
    issues = []
    if not doc.doc_date:
        issues.append("Не указана дата документа")
    if not doc.document_author:
        issues.append("Не указан автор документа")
    if not doc.description:
        issues.append("Нет краткого описания")
    if not doc.extracted_text:
        issues.append("Нет OCR/извлеченного текста")
    if not doc.retention_category:
        issues.append("Не заполнена категория хранения")
    if not doc.checksum_sha256:
        issues.append("Не рассчитана контрольная сумма")

    score = max(0, 100 - len(issues) * 15)
    return {
        "score": score,
        "issues": issues,
        "is_strong": score >= 80,
    }
