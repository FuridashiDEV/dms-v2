from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    MatchAny,
)


from qdrant_client import QdrantClient
from django.conf import settings

COLLECTION_NAME = "documents"
VECTOR_SIZE = 384

_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    global _client

    if _client is None:
        _client = QdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
        )

    return _client





from django.conf import settings

# ======================================================
# CONFIG
# ======================================================

COLLECTION_NAME = "documents"
VECTOR_SIZE = 384   # all-MiniLM-L6-v2

# ======================================================
# CLIENT (SINGLETON)
# ======================================================

_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    global _client

    if _client is None:
        _client = QdrantClient(
            host=getattr(settings, "QDRANT_HOST", "localhost"),
            port=getattr(settings, "QDRANT_PORT", 6333),
        )

    return _client


# ======================================================
# COLLECTION
# ======================================================

_collection_ready = False


def ensure_collection() -> None:
    global _collection_ready

    if _collection_ready:
        return

    client = get_client()

    try:
        collections = client.get_collections().collections
    except Exception:
        # Qdrant может быть недоступен — не падаем
        return

    if COLLECTION_NAME not in {c.name for c in collections}:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=VECTOR_SIZE,
                distance=Distance.COSINE,
            ),
        )

    _collection_ready = True


# ======================================================
# UPSERT
# ======================================================

def upsert_document(
    *,
    doc_id: int,
    vector: list[float],
    payload: dict,
) -> None:
    if not vector or len(vector) != VECTOR_SIZE:
        return

    ensure_collection()
    client = get_client()

    client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            PointStruct(
                id=doc_id,
                vector=vector,
                payload=payload,
            )
        ],
    )


# ======================================================
# DELETE
# ======================================================

def delete_document(doc_id: int) -> None:
    if not doc_id:
        return

    ensure_collection()
    client = get_client()

    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=[doc_id],
    )


# ======================================================
# SEARCH
# ======================================================

from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

def search_documents(
    *,
    embedding: list[float],
    limit: int = 30,
    filters: dict | None = None,
) -> list[dict]:

    if not embedding:
        return []

    ensure_collection()
    client = get_client()

    q_filter = None

    if filters:
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

        if conditions:
            q_filter = Filter(must=conditions)

    result = client.query_points(
        collection_name=COLLECTION_NAME,
        query=embedding,
        limit=limit,
        with_payload=True,
        query_filter=q_filter,
    )

    return [
        {
            "id": point.id,
            "score": point.score,
            "payload": point.payload,
        }
        for point in result.points
    ]