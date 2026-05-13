from __future__ import annotations

import threading
from typing import List, Optional

from django.conf import settings
from sentence_transformers import SentenceTransformer


_model: Optional[SentenceTransformer] = None
_model_name: str | None = None
_lock = threading.Lock()

MAX_CHARS = 8000


def get_embedding_model_name() -> str:
    return getattr(settings, "SEARCH_EMBEDDING_MODEL", "all-MiniLM-L6-v2")


def get_embedding_vector_size() -> int:
    return getattr(settings, "SEARCH_EMBEDDING_VECTOR_SIZE", 384)


def _get_model() -> SentenceTransformer:
    global _model, _model_name

    configured_model = get_embedding_model_name()
    if _model is None or _model_name != configured_model:
        with _lock:
            if _model is None or _model_name != configured_model:
                _model = SentenceTransformer(configured_model)
                _model_name = configured_model

    return _model


def build_embedding(text: str) -> List[float]:
    if not isinstance(text, str):
        return []

    text = text.strip()
    if not text:
        return []

    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]

    try:
        model = _get_model()
        vec = model.encode(
            text,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        vector = vec.tolist()
        expected_size = get_embedding_vector_size()
        if expected_size and len(vector) != expected_size:
            return []
        return vector
    except Exception:
        return []


def build_embeddings_batch(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []

    clean_texts = [
        text[:MAX_CHARS] if isinstance(text, str) and text.strip() else ""
        for text in texts
    ]

    try:
        model = _get_model()
        vectors = model.encode(
            clean_texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=32,
        )
        expected_size = get_embedding_vector_size()
        results = []
        for vector in vectors:
            values = vector.tolist()
            results.append(values if not expected_size or len(values) == expected_size else [])
        return results
    except Exception:
        return [[] for _ in texts]
