from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from dms.models import Document
from dms.services.embedding import build_embeddings_batch, get_embedding_model_name
from dms.services.index_versions import (
    build_document_index_fingerprint,
    cleanup_stale_points_for_document,
    get_active_search_index_version,
    get_document_index_state,
    get_latest_document_version,
    record_document_index_failure,
    record_document_index_success,
)
from dms.services.search_intelligence import (
    build_document_search_text,
    chunk_text,
    update_document_search_metadata,
)
from dms.services.vector_store import delete_document, make_point_id, upsert_document_chunks


logger = logging.getLogger(__name__)


def build_document_index_payload(
    document: Document,
    *,
    chunk_key: str,
    chunk_kind: str,
    text: str,
    document_version_id: int | None,
    index_version_id: int,
    qdrant_collection: str,
) -> dict:
    return {
        "document_id": document.id,
        "document_version_id": document_version_id,
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
        "search_index_version_id": index_version_id,
        "search_index_version": getattr(settings, "SEARCH_INDEX_VERSION", 2),
        "qdrant_collection": qdrant_collection,
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
    for _entity_type, values in sorted((entities.get("entities_by_type") or {}).items()):
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
        index_version = get_active_search_index_version()
        document_version = get_latest_document_version(document)
        previous_state = get_document_index_state(document, index_version=index_version)
        previous_point_ids = list(previous_state.point_ids) if previous_state else []
        update_document_search_metadata(document)
        chunks = build_document_index_chunks(document)
        content_hash = build_document_index_fingerprint(
            document,
            document_version=document_version,
            chunks=chunks,
        )
        vectors = build_embeddings_batch([chunk["text"] for chunk in chunks])
        vector_chunks = []
        for chunk, vector in zip(chunks, vectors):
            if not vector:
                continue
            point_id = make_point_id(
                doc_id=document.id,
                document_version_id=document_version.id if document_version else None,
                chunk_key=chunk["key"],
                index_version_id=index_version.id,
                collection_name=index_version.qdrant_collection,
            )
            vector_chunks.append(
                {
                    "point_id": point_id,
                    "vector": vector,
                    "payload": build_document_index_payload(
                        document,
                        chunk_key=chunk["key"],
                        chunk_kind=chunk["kind"],
                        text=chunk["text"],
                        document_version_id=document_version.id if document_version else None,
                        index_version_id=index_version.id,
                        qdrant_collection=index_version.qdrant_collection,
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
            record_document_index_failure(
                document=document,
                index_version=index_version,
                document_version=document_version,
                error="No valid vectors were produced for document chunks.",
            )
            return False
        indexed = upsert_document_chunks(chunks=vector_chunks)
        if not indexed:
            record_document_index_failure(
                document=document,
                index_version=index_version,
                document_version=document_version,
                error="Qdrant upsert failed or collection is unavailable.",
            )
            return False

        point_ids = [chunk["point_id"] for chunk in vector_chunks]
        record_document_index_success(
            document=document,
            index_version=index_version,
            document_version=document_version,
            chunks_count=len(vector_chunks),
            point_ids=point_ids,
            content_hash=content_hash,
        )
        cleanup_stale_points_for_document(
            document=document,
            current_point_ids=point_ids,
            previous_point_ids=previous_point_ids,
            index_version=index_version,
        )
        return True
    except Exception:
        logger.exception("Failed to index document", extra={"document_id": getattr(document, "id", None)})
        return False


def delete_document_from_index(document_id: int) -> bool:
    try:
        return delete_document(document_id)
    except Exception:
        logger.exception("Failed to delete document from vector index", extra={"document_id": document_id})
        return False
