from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from dms.models import Document
from dms.services.embedding import build_embeddings_batch, get_embedding_model_name
from dms.services.search_intelligence import (
    build_document_search_text,
    chunk_text,
    update_document_search_metadata,
)
from dms.services.vector_store import delete_document, make_point_id, upsert_document_chunks


logger = logging.getLogger(__name__)


def build_document_index_payload(document: Document, *, chunk_key: str, chunk_kind: str, text: str) -> dict:
    return {
        "document_id": document.id,
        "chunk_key": chunk_key,
        "chunk_kind": chunk_kind,
        "text_preview": text[:320],
        "title": document.title,
        "organization_id": document.organization_id,
        "department_id": document.department_id,
        "folder_id": document.folder_id,
        "doc_type_id": document.doc_type_id,
        "doc_type": document.doc_type.name if document.doc_type else "",
        "doc_date": document.doc_date.isoformat() if document.doc_date else None,
        "entities": document.search_entities or {},
        "embedding_model": get_embedding_model_name(),
        "search_index_version": getattr(settings, "SEARCH_INDEX_VERSION", 2),
    }


def build_document_index_chunks(document: Document) -> list[dict]:
    normalized_text = document.search_text_normalized or build_document_search_text(document)
    entities = document.search_entities or {}
    entity_parts = [
        entities.get("document_type", ""),
        entities.get("counterparty", ""),
        entities.get("subject", ""),
        entities.get("document_number", ""),
        entities.get("document_date", ""),
        entities.get("bin_iin", ""),
        entities.get("contract_reference", ""),
        entities.get("amount", {}).get("raw", ""),
        str(entities.get("amount", {}).get("value", "")),
        " ".join(entities.get("key_phrases", [])),
    ]
    for key in ("goods", "services", "works", "legal_form", "organization_name", "currency"):
        values = entities.get(key) or []
        if isinstance(values, str):
            entity_parts.append(values)
        else:
            entity_parts.extend(str(value) for value in values if value)
    for values in entities.get("entities_by_type", {}).values():
        for item in values:
            if isinstance(item, dict):
                entity_parts.extend(str(item.get(key, "")) for key in ("value", "normalized", "raw") if item.get(key))
    normalization = entities.get("normalization") or {}
    entity_parts.append(normalization.get("normalized_value", ""))
    entity_parts.extend(normalization.get("variants", []))
    for correction in normalization.get("corrections", []):
        if isinstance(correction, dict):
            entity_parts.extend(
                str(correction.get(key, ""))
                for key in ("raw_value", "normalized_value")
                if correction.get(key)
            )
    entity_text = " ".join(filter(None, entity_parts))
    chunks = [
        {
            "key": "title",
            "kind": "title",
            "text": " ".join(filter(None, [document.title, document.doc_type.name if document.doc_type else ""])),
        },
        {
            "key": "metadata",
            "kind": "metadata",
            "text": " ".join(
                filter(
                    None,
                    [
                        document.description,
                        document.document_author,
                        document.source_file_name,
                        document.folder.name if document.folder else "",
                    ],
                )
            ),
        },
        {
            "key": "entities",
            "kind": "entities",
            "text": entity_text,
        },
    ]
    for index, text in enumerate(chunk_text(normalized_text), start=1):
        chunks.append(
            {
                "key": f"content-{index}",
                "kind": "content",
                "text": text,
            }
        )
    return [chunk for chunk in chunks if chunk["text"].strip()]


def index_document(document: Document) -> bool:
    try:
        document = (
            Document.objects
            .select_related("organization", "department", "folder", "doc_type")
            .get(pk=document.pk)
        )
        update_document_search_metadata(document)
        chunks = build_document_index_chunks(document)
        vectors = build_embeddings_batch([chunk["text"] for chunk in chunks])
        vector_chunks = []
        for chunk, vector in zip(chunks, vectors):
            if not vector:
                continue
            vector_chunks.append(
                {
                    "point_id": make_point_id(doc_id=document.id, chunk_key=chunk["key"]),
                    "vector": vector,
                    "payload": build_document_index_payload(
                        document,
                        chunk_key=chunk["key"],
                        chunk_kind=chunk["kind"],
                        text=chunk["text"],
                    ),
                }
            )

        updated_fields = [
            "search_text_normalized",
            "search_entities",
            "search_embedding_model",
            "search_index_version",
            "search_indexed_at",
        ]
        document.search_embedding_model = get_embedding_model_name()
        document.search_index_version = getattr(settings, "SEARCH_INDEX_VERSION", 2)
        document.search_indexed_at = timezone.now()
        document.save(update_fields=updated_fields)

        if not vector_chunks:
            return False
        delete_document(document.id)
        return upsert_document_chunks(chunks=vector_chunks)
    except Exception:
        logger.exception("Failed to index document", extra={"document_id": getattr(document, "id", None)})
        return False


def delete_document_from_index(document_id: int) -> bool:
    try:
        return delete_document(document_id)
    except Exception:
        logger.exception("Failed to delete document from vector index", extra={"document_id": document_id})
        return False
