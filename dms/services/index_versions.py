from __future__ import annotations

import hashlib
import json
from typing import Iterable

from django.conf import settings
from django.utils import timezone

from dms.models import Document, DocumentSearchIndexState, DocumentVersion, SearchIndexVersion
from dms.services.embedding import get_embedding_model_name, get_embedding_vector_size


def get_active_search_index_version() -> SearchIndexVersion:
    embedding_model = get_embedding_model_name()
    embedding_dimension = get_embedding_vector_size()
    chunking_version = getattr(settings, "SEARCH_CHUNKING_VERSION", "chunking-v1")
    normalization_version = getattr(settings, "SEARCH_NORMALIZATION_VERSION", "normalization-v1")
    qdrant_collection = getattr(settings, "QDRANT_COLLECTION", "documents")

    conflicting = SearchIndexVersion.objects.filter(
        qdrant_collection=qdrant_collection,
        is_active=True,
    ).exclude(
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
    )
    if conflicting.exists():
        raise ValueError(
            "Active search index versions for one Qdrant collection must use one embedding model and dimension."
        )

    version, _created = SearchIndexVersion.objects.get_or_create(
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        chunking_version=chunking_version,
        normalization_version=normalization_version,
        qdrant_collection=qdrant_collection,
        defaults={"is_active": True},
    )
    if not version.is_active:
        version.is_active = True
        version.save(update_fields=["is_active"])
    return version


def get_latest_document_version(document: Document) -> DocumentVersion | None:
    return document.versions.order_by("-number", "-created_at", "-id").first()


def build_document_index_fingerprint(
    document: Document,
    *,
    document_version: DocumentVersion | None,
    chunks: list[dict],
) -> str:
    payload = {
        "document_id": document.id,
        "document_version_id": document_version.id if document_version else None,
        "checksum_sha256": document.checksum_sha256,
        "title": document.title,
        "description": document.description,
        "doc_type_id": document.doc_type_id,
        "doc_date": document.doc_date.isoformat() if document.doc_date else None,
        "department_id": document.department_id,
        "folder_id": document.folder_id,
        "language": document.language,
        "extracted_text": document.extracted_text,
        "search_text_normalized": document.search_text_normalized,
        "search_entities": document.search_entities,
        "chunks": [{"key": chunk["key"], "kind": chunk["kind"], "text": chunk["text"]} for chunk in chunks],
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def get_document_index_state(
    document: Document,
    *,
    index_version: SearchIndexVersion | None = None,
) -> DocumentSearchIndexState | None:
    index_version = index_version or get_active_search_index_version()
    return DocumentSearchIndexState.objects.filter(document=document, index_version=index_version).first()


def is_document_index_stale(
    document: Document,
    *,
    index_version: SearchIndexVersion | None = None,
    chunks: list[dict] | None = None,
) -> bool:
    index_version = index_version or get_active_search_index_version()
    document_version = get_latest_document_version(document)
    state = get_document_index_state(document, index_version=index_version)
    if state is None or state.status != DocumentSearchIndexState.Status.INDEXED:
        return True
    if state.qdrant_collection != index_version.qdrant_collection:
        return True
    if state.document_version_id != (document_version.id if document_version else None):
        return True
    if chunks is None:
        from dms.services.document_indexing import build_document_index_chunks

        chunks = build_document_index_chunks(document)
    current_hash = build_document_index_fingerprint(
        document,
        document_version=document_version,
        chunks=chunks,
    )
    return state.content_hash != current_hash


def mark_document_index_stale(
    document: Document,
    *,
    reason: str = "",
    index_version: SearchIndexVersion | None = None,
) -> DocumentSearchIndexState:
    index_version = index_version or get_active_search_index_version()
    state, _created = DocumentSearchIndexState.objects.get_or_create(
        document=document,
        index_version=index_version,
        defaults={
            "organization": document.organization,
            "document_version": get_latest_document_version(document),
            "qdrant_collection": index_version.qdrant_collection,
            "status": DocumentSearchIndexState.Status.STALE,
            "last_error": reason[:4000],
        },
    )
    if state.status != DocumentSearchIndexState.Status.STALE or reason:
        state.status = DocumentSearchIndexState.Status.STALE
        state.last_error = reason[:4000]
        state.save(update_fields=["status", "last_error", "updated_at"])
    return state


def record_document_index_success(
    *,
    document: Document,
    index_version: SearchIndexVersion,
    document_version: DocumentVersion | None,
    chunks_count: int,
    point_ids: list[str],
    content_hash: str,
) -> DocumentSearchIndexState:
    state, _created = DocumentSearchIndexState.objects.update_or_create(
        document=document,
        index_version=index_version,
        defaults={
            "organization": document.organization,
            "document_version": document_version,
            "status": DocumentSearchIndexState.Status.INDEXED,
            "indexed_at": timezone.now(),
            "chunks_count": chunks_count,
            "qdrant_collection": index_version.qdrant_collection,
            "content_hash": content_hash,
            "point_ids": point_ids,
            "last_error": "",
        },
    )
    return state


def record_document_index_failure(
    *,
    document: Document,
    index_version: SearchIndexVersion,
    document_version: DocumentVersion | None,
    error: str,
) -> DocumentSearchIndexState:
    state, _created = DocumentSearchIndexState.objects.update_or_create(
        document=document,
        index_version=index_version,
        defaults={
            "organization": document.organization,
            "document_version": document_version,
            "status": DocumentSearchIndexState.Status.FAILED,
            "qdrant_collection": index_version.qdrant_collection,
            "last_error": error[:4000],
        },
    )
    return state


def stale_document_queryset(queryset, *, index_version: SearchIndexVersion | None = None):
    index_version = index_version or get_active_search_index_version()
    indexed_document_ids = DocumentSearchIndexState.objects.filter(
        index_version=index_version,
        status=DocumentSearchIndexState.Status.INDEXED,
    ).values_list("document_id", flat=True)
    return queryset.exclude(id__in=indexed_document_ids)


def cleanup_stale_points_for_document(
    *,
    document: Document,
    current_point_ids: Iterable[str],
    index_version: SearchIndexVersion,
    previous_point_ids: Iterable[str] | None = None,
) -> bool:
    from dms.services.vector_store import delete_points

    keep = set(current_point_ids)
    stale_point_ids: list[str] = []
    if previous_point_ids:
        stale_point_ids.extend(point_id for point_id in previous_point_ids if point_id not in keep)
    stale_states = DocumentSearchIndexState.objects.filter(
        document=document,
        qdrant_collection=index_version.qdrant_collection,
    ).exclude(index_version=index_version)
    for state in stale_states:
        stale_point_ids.extend(point_id for point_id in state.point_ids if point_id not in keep)

    if not stale_point_ids:
        return True
    return delete_points(point_ids=stale_point_ids)
