import logging

from django.conf import settings
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)


logger = logging.getLogger(__name__)

COLLECTION_NAME = getattr(settings, "QDRANT_COLLECTION", "documents")
VECTOR_SIZE = 384

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
        return False

    _collection_ready = True
    return True


def upsert_document(
    *,
    doc_id: int,
    vector: list[float],
    payload: dict,
) -> bool:
    if not vector or len(vector) != VECTOR_SIZE:
        return False

    if not ensure_collection():
        return False

    try:
        get_client().upsert(
            collection_name=COLLECTION_NAME,
            points=[
                PointStruct(
                    id=doc_id,
                    vector=vector,
                    payload=payload,
                )
            ],
        )
    except Exception:
        logger.warning("Qdrant upsert failed", exc_info=True, extra={"document_id": doc_id})
        return False

    return True


def delete_document(doc_id: int) -> bool:
    if not doc_id:
        return False

    if not ensure_collection():
        return False

    try:
        get_client().delete(
            collection_name=COLLECTION_NAME,
            points_selector=[doc_id],
        )
    except Exception:
        logger.warning("Qdrant delete failed", exc_info=True, extra={"document_id": doc_id})
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
            conditions.append(
                FieldCondition(
                    key=field,
                    match=MatchAny(any=list(value)),
                )
            )
        else:
            conditions.append(
                FieldCondition(
                    key=field,
                    match=MatchValue(value=value),
                )
            )

    if not conditions:
        return None

    return Filter(must=conditions)


def search_documents(
    *,
    embedding: list[float] | None = None,
    query_vector: list[float] | None = None,
    limit: int = 30,
    filters: dict | None = None,
    department_ids: list[int] | None = None,
) -> list[dict]:
    vector = embedding if embedding is not None else query_vector
    if not vector:
        return []

    if department_ids is not None:
        filters = {
            **(filters or {}),
            "department_id": department_ids,
        }

    if not ensure_collection():
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
        return []

    return [
        {
            "id": point.id,
            "score": point.score,
            "payload": point.payload,
        }
        for point in result.points
    ]
