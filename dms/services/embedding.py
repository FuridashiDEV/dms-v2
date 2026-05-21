from __future__ import annotations

from typing import List

from django.conf import settings

MAX_CHARS = 8000


def get_embedding_model_name() -> str:
    return getattr(settings, "SEARCH_EMBEDDING_MODEL", "BAAI/bge-m3")


def get_embedding_vector_size() -> int:
    from dms.services.model_stack import expected_embedding_dimension

    configured = getattr(settings, "SEARCH_EMBEDDING_VECTOR_SIZE", None)
    if configured:
        return int(configured)
    return expected_embedding_dimension(get_embedding_model_name())


def build_embedding(text: str) -> List[float]:
    """Build a query embedding for existing search call sites."""
    if not isinstance(text, str):
        return []

    text = text.strip()
    if not text:
        return []

    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]

    from dms.services.model_stack import get_embedding_adapter

    return get_embedding_adapter(get_embedding_model_name()).encode_query(text)


def build_document_embedding(text: str) -> List[float]:
    if not isinstance(text, str):
        return []
    text = text.strip()
    if not text:
        return []
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]

    from dms.services.model_stack import get_embedding_adapter

    vectors = get_embedding_adapter(get_embedding_model_name()).encode_documents([text])
    return vectors[0] if vectors else []


def build_embeddings_batch(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []

    clean_texts = [
        text[:MAX_CHARS] if isinstance(text, str) and text.strip() else ""
        for text in texts
    ]

    from dms.services.model_stack import get_embedding_adapter

    return get_embedding_adapter(get_embedding_model_name()).encode_documents(clean_texts)
