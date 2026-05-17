from __future__ import annotations

import logging
import time
import uuid

from django.conf import settings
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)


logger = logging.getLogger(__name__)

COLLECTION_NAME = getattr(settings, "QDRANT_COLLECTION", "documents_all_minilm_l6_v2")
VECTOR_SIZE = getattr(settings, "SEARCH_EMBEDDING_VECTOR_SIZE", 384)

_client: QdrantClient | None = None
_collection_ready = False


def get_client() -> QdrantClient:
    global _client

    if _client is None:
        _client = QdrantClient(
            host=getattr(settings, "QDRANT_HOST", "localhost"),
            port=getattr(settings, "QDRANT_PORT", 6333),
        )

    return _client


def ensure_collection() -> bool:
    global _collection_ready

    if _collection_ready:
        return True

    try:
        client = get_client()
        collections = client.get_collections().collections
        if COLLECTION_NAME not in {collection.name for collection in collections}:
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=VECTOR_SIZE,
                    distance=Distance.COSINE,
                ),
            )
    except Exception:
        logger.warning("Qdrant collection is not available", exc_info=True)
        try:
            from dms.services.observability import record_qdrant_availability

            record_qdrant_availability(available=False)
        except Exception:
            pass
        return False

    _collection_ready = True
    try:
        from dms.services.observability import record_qdrant_availability

        record_qdrant_availability(available=True)
    except Exception:
        pass
    return True


def make_point_id(
    *,
    doc_id: int,
    chunk_key: str,
    document_version_id: int | None = None,
    index_version_id: int | None = None,
    collection_name: str | None = None,
) -> str:
    collection = collection_name or COLLECTION_NAME
    version_part = document_version_id if document_version_id is not None else "no-version"
    index_part = index_version_id if index_version_id is not None else "legacy-index"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{collection}:{doc_id}:{version_part}:{chunk_key}:{index_part}"))


def _valid_vector(vector: list[float]) -> bool:
    return bool(vector) and len(vector) == VECTOR_SIZE


def upsert_document(
    *,
    doc_id: int,
    vector: list[float],
    payload: dict,
) -> bool:
    if not _valid_vector(vector):
        return False

    payload = {
        **payload,
        "document_id": doc_id,
        "chunk_key": payload.get("chunk_key", "document"),
        "embedding_model": getattr(settings, "SEARCH_EMBEDDING_MODEL", ""),
    }
    return upsert_document_chunks(
        chunks=[
            {
                "point_id": doc_id,
                "vector": vector,
                "payload": payload,
            }
        ]
    )


def upsert_document_chunks(*, chunks: list[dict]) -> bool:
    points = []
    for chunk in chunks:
        vector = chunk.get("vector") or []
        if not _valid_vector(vector):
            continue
        points.append(
            PointStruct(
                id=chunk["point_id"],
                vector=vector,
                payload=chunk.get("payload") or {},
            )
        )

    if not points:
        return False
    if not ensure_collection():
        return False

    try:
        get_client().upsert(
            collection_name=COLLECTION_NAME,
            points=points,
        )
    except Exception:
        logger.warning("Qdrant upsert failed", exc_info=True)
        return False

    return True


def delete_document(doc_id: int) -> bool:
    if not doc_id:
        return False
    if not ensure_collection():
        return False

    try:
        client = get_client()
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=[doc_id],
        )
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=doc_id),
                        )
                    ]
                )
            ),
        )
    except Exception:
        logger.warning("Qdrant delete failed", exc_info=True, extra={"document_id": doc_id})
        return False

    return True


def delete_points(*, point_ids: list[str]) -> bool:
    point_ids = [point_id for point_id in point_ids if point_id]
    if not point_ids:
        return True
    if not ensure_collection():
        return False

    try:
        get_client().delete(
            collection_name=COLLECTION_NAME,
            points_selector=point_ids,
        )
    except Exception:
        logger.warning("Qdrant point cleanup failed", exc_info=True)
        return False

    return True


def _build_filter(filters: dict | None) -> Filter | None:
    if not filters:
        return None

    conditions = []
    for field, value in filters.items():
        if value is None:
            continue

        if isinstance(value, (list, tuple, set)):
            values = [item for item in value if item is not None]
            if not values:
                continue
            conditions.append(
                FieldCondition(
                    key=field,
                    match=MatchAny(any=values),
                )
            )
        else:
            conditions.append(
                FieldCondition(
                    key=field,
                    match=MatchValue(value=value),
                )
            )

    return Filter(must=conditions) if conditions else None


def search_documents(
    *,
    embedding: list[float] | None = None,
    query_vector: list[float] | None = None,
    limit: int = 30,
    filters: dict | None = None,
    department_ids: list[int] | None = None,
) -> list[dict]:
    started = time.perf_counter()
    organization_ids = _organization_ids_from_filters(filters)
    vector = embedding if embedding is not None else query_vector
    if not vector:
        return []

    if department_ids is not None:
        filters = {
            **(filters or {}),
            "department_id": department_ids,
        }

    if not ensure_collection():
        _record_search_observability(
            organization_ids=organization_ids,
            started=started,
            degraded=True,
            result_count=0,
        )
        return []

    try:
        result = get_client().query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            limit=limit,
            with_payload=True,
            query_filter=_build_filter(filters),
        )
    except Exception:
        logger.warning("Qdrant search failed", exc_info=True)
        _record_search_observability(
            organization_ids=organization_ids,
            started=started,
            degraded=True,
            result_count=0,
        )
        return []

    results = [
        {
            "id": point.id,
            "document_id": (point.payload or {}).get("document_id") or point.id,
            "score": point.score,
            "payload": point.payload,
        }
        for point in result.points
    ]
    _record_search_observability(
        organization_ids=organization_ids,
        started=started,
        degraded=False,
        result_count=len(results),
    )
    return results


def _organization_ids_from_filters(filters: dict | None) -> list[int]:
    value = (filters or {}).get("organization_id")
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    ids = []
    for item in values:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _record_search_observability(
    *,
    organization_ids: list[int],
    started: float,
    degraded: bool,
    result_count: int,
) -> None:
    try:
        from dms.services.observability import record_search_latency

        record_search_latency(
            organization_ids=organization_ids,
            latency_ms=(time.perf_counter() - started) * 1000,
            degraded=degraded,
            result_count=result_count,
        )
    except Exception:
        pass
