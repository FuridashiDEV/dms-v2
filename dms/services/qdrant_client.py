from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams
from django.conf import settings

COLLECTION_NAME = settings.QDRANT_COLLECTION
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


def ensure_collection() -> None:
    client = get_client()

    collections = client.get_collections().collections
    if COLLECTION_NAME in {c.name for c in collections}:
        return

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(
            size=VECTOR_SIZE,
            distance=Distance.COSINE,
        ),
    )
