from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import re
from typing import Any, Iterable

from django.db import transaction

from dms.models import Organization, RetentionPolicy, SensitiveEntity


SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "authorization",
    "access_key",
    "private_key",
    "file_path",
    "filepath",
    "path",
    "full_text",
    "extracted_text",
    "document_text",
    "raw_text",
    "content",
    "payload",
    "query",
)


@dataclass(frozen=True)
class DetectedSensitiveEntity:
    entity_type: str
    raw_value_hash: str
    masked_value: str
    confidence: Decimal
    source: str = ""


def detect_sensitive_entities(
    text: str,
    *,
    organization: Organization | None = None,
    document=None,
    source: str = "manual",
    persist: bool = False,
) -> list[DetectedSensitiveEntity]:
    detected = _dedupe(
        [
            *_detect_iin_bin(text),
            *_detect_emails(text),
            *_detect_phones(text),
            *_detect_amounts(text),
            *_detect_personal_names(text),
        ],
        source=source,
    )
    if persist and detected and organization is not None:
        persist_sensitive_entities(
            detected,
            organization=organization,
            document=document,
            source=source,
        )
    return detected


@transaction.atomic
def persist_sensitive_entities(
    entities: Iterable[DetectedSensitiveEntity],
    *,
    organization: Organization,
    document=None,
    source: str = "manual",
) -> list[SensitiveEntity]:
    saved = []
    for entity in entities:
        item, _created = SensitiveEntity.objects.update_or_create(
            organization=organization,
            document=document,
            entity_type=entity.entity_type,
            raw_value_hash=entity.raw_value_hash,
            source=source,
            defaults={
                "masked_value": entity.masked_value,
                "confidence": entity.confidence,
                "context": {
                    "source": source,
                    "raw_value_stored": False,
                },
            },
        )
        saved.append(item)
    return saved


def summarize_sensitive_entities(entities: Iterable[DetectedSensitiveEntity]) -> dict[str, int]:
    return dict(Counter(entity.entity_type for entity in entities))


def sanitize_governance_metadata(value: Any, *, max_string_length: int = 240) -> Any:
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                safe[key_text] = "[redacted]"
                continue
            safe[key_text] = sanitize_governance_metadata(item, max_string_length=max_string_length)
        return safe
    if isinstance(value, list):
        return [sanitize_governance_metadata(item, max_string_length=max_string_length) for item in value[:50]]
    if isinstance(value, tuple):
        return [sanitize_governance_metadata(item, max_string_length=max_string_length) for item in value[:50]]
    if isinstance(value, str):
        return _sanitize_text_value(value, max_string_length=max_string_length)
    return value


def build_safe_processing_metadata(document, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = {
        "document": {
            "id": document.id,
            "public_id": str(document.public_id) if document.public_id else "",
            "status": document.status,
            "checksum_sha256": document.checksum_sha256,
            "extracted_text_length": len(document.extracted_text or ""),
            "has_file": bool(document.file),
        },
        "organization": {
            "id": document.organization_id,
        },
    }
    if payload:
        metadata["payload_summary"] = sanitize_governance_metadata(payload)
    return metadata


def ensure_default_retention_policies(organization: Organization | None = None) -> list[RetentionPolicy]:
    defaults = [
        (RetentionPolicy.Scope.DOCUMENT, "Documents - review before disposition", 3650),
        (RetentionPolicy.Scope.VERSION, "Document versions - preserve with document", 3650),
        (RetentionPolicy.Scope.AUDIT, "Audit events - security history", 2555),
        (RetentionPolicy.Scope.PROCESSING_RESULT, "Processing results - periodic review", 365),
        (RetentionPolicy.Scope.TEMPORARY_FILE, "Temporary files - short review window", 30),
    ]
    policies = []
    for scope, name, days in defaults:
        policy, _created = RetentionPolicy.objects.get_or_create(
            organization=organization,
            scope=scope,
            name=name,
            defaults={
                "retention_days": days,
                "action": RetentionPolicy.Action.REVIEW_ONLY,
                "notes": "Foundation policy only. No automatic deletion is performed without explicit approval.",
            },
        )
        policies.append(policy)
    return policies


def _detect_iin_bin(text: str) -> list[DetectedSensitiveEntity]:
    entities = []
    for match in re.finditer(r"(?<!\d)(\d{12})(?!\d)", text or ""):
        value = match.group(1)
        prefix = (text[max(0, match.start() - 20): match.start()] or "").lower()
        entity_type = SensitiveEntity.EntityType.BIN if "бин" in prefix or "bin" in prefix else SensitiveEntity.EntityType.IIN
        entities.append(_entity(entity_type, value, confidence=Decimal("0.86")))
    return entities


def _detect_emails(text: str) -> list[DetectedSensitiveEntity]:
    return [
        _entity(SensitiveEntity.EntityType.EMAIL, match.group(0), confidence=Decimal("0.94"))
        for match in re.finditer(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text or "", flags=re.IGNORECASE)
    ]


def _detect_phones(text: str) -> list[DetectedSensitiveEntity]:
    pattern = r"(?<!\w)(?:\+?7|8)?[\s\-()]*(?:\d[\s\-()]*){10}(?!\w)"
    return [
        _entity(SensitiveEntity.EntityType.PHONE, match.group(0), confidence=Decimal("0.82"))
        for match in re.finditer(pattern, text or "")
    ]


def _detect_amounts(text: str) -> list[DetectedSensitiveEntity]:
    pattern = r"(?<!\w)(\d[\d\s.,]{2,})\s*(?:kzt|тенге|тг|₸|usd|eur)?(?!\w)"
    return [
        _entity(SensitiveEntity.EntityType.AMOUNT, match.group(0), confidence=Decimal("0.72"))
        for match in re.finditer(pattern, text or "", flags=re.IGNORECASE)
        if len(re.sub(r"\D", "", match.group(0))) >= 4
    ]


def _detect_personal_names(text: str) -> list[DetectedSensitiveEntity]:
    pattern = r"\b(?:ФИО|fio|имя)\s*[:\-]\s*([A-ZА-ЯЁ][A-Za-zА-Яа-яЁё'\-]+(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё'\-]+){1,2})"
    return [
        _entity(SensitiveEntity.EntityType.PERSONAL_NAME, match.group(1), confidence=Decimal("0.68"))
        for match in re.finditer(pattern, text or "", flags=re.IGNORECASE)
    ]


def _entity(entity_type: str, raw_value: str, *, confidence: Decimal) -> DetectedSensitiveEntity:
    normalized = " ".join(str(raw_value or "").split())
    return DetectedSensitiveEntity(
        entity_type=entity_type,
        raw_value_hash=_hash_value(normalized),
        masked_value=_mask_value(normalized),
        confidence=confidence,
    )


def _dedupe(entities: list[DetectedSensitiveEntity], *, source: str) -> list[DetectedSensitiveEntity]:
    seen = set()
    result = []
    for entity in entities:
        key = (entity.entity_type, entity.raw_value_hash)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            DetectedSensitiveEntity(
                entity_type=entity.entity_type,
                raw_value_hash=entity.raw_value_hash,
                masked_value=entity.masked_value,
                confidence=entity.confidence,
                source=source,
            )
        )
    return result


def _hash_value(value: str) -> str:
    return hashlib.sha256((value or "").strip().lower().encode("utf-8")).hexdigest()


def _mask_value(value: str) -> str:
    value = " ".join(str(value or "").split())
    if "@" in value:
        local, _, domain = value.partition("@")
        return f"{local[:2]}***@{domain[:2]}***"
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 8:
        return f"{digits[:2]}***{digits[-4:]}"
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _sanitize_text_value(value: str, *, max_string_length: int) -> str:
    sanitized = value
    for entity in detect_sensitive_entities(value):
        sanitized = sanitized.replace(entity.masked_value, "[sensitive]")
    sanitized = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[email]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"(?<!\d)\d{12}(?!\d)", "[id-number]", sanitized)
    sanitized = re.sub(r"(?<!\w)(?:\+?7|8)?[\s\-()]*(?:\d[\s\-()]*){10}(?!\w)", "[phone]", sanitized)
    sanitized = re.sub(r"(?i)(token|secret|password|api[_-]?key|authorization)\s*[:=]\s*[\w\-.:/+=]+", r"\1=[redacted]", sanitized)
    sanitized = re.sub(r"(?i)([a-z]:\\|/)[^\s]+", "[path]", sanitized)
    sanitized = " ".join(sanitized.split())
    if len(sanitized) > max_string_length:
        sanitized = sanitized[: max_string_length - 3].rstrip() + "..."
    return sanitized
