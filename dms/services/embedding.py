# dms/services/embedding.py

from sentence_transformers import SentenceTransformer
from typing import List, Optional
import threading

# ======================================================
# MODEL (LAZY + THREAD-SAFE)
# ======================================================

_model: Optional[SentenceTransformer] = None
_lock = threading.Lock()

MODEL_NAME = "all-MiniLM-L6-v2"
MAX_CHARS = 8000   # защита от OCR-мусора


def _get_model() -> SentenceTransformer:
    """
    Лениво загружает модель.
    Гарантирует один инстанс на процесс.
    """
    global _model

    if _model is None:
        with _lock:
            if _model is None:
                _model = SentenceTransformer(MODEL_NAME)

    return _model


# ======================================================
# SINGLE EMBEDDING
# ======================================================

def build_embedding(text: str) -> List[float]:
    """
    Строит embedding для одного документа.

    ГАРАНТИИ:
    - всегда возвращает list[float]
    - никогда не падает
    - нормализует вектор (важно для cosine)
    """

    if not isinstance(text, str):
        return []

    text = text.strip()
    if not text:
        return []

    # ограничиваем размер
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]

    try:
        model = _get_model()
        vec = model.encode(
            text,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vec.tolist()

    except Exception:
        return []


# ======================================================
# BATCH EMBEDDINGS (ДЛЯ МИГРАЦИЙ / REINDEX)
# ======================================================

def build_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """
    Batch-версия для массовой индексации.
    Использовать для:
    - миграций
    - переиндексации
    """

    if not texts:
        return []

    clean_texts = []
    for t in texts:
        if isinstance(t, str) and t.strip():
            clean_texts.append(t[:MAX_CHARS])
        else:
            clean_texts.append("")

    try:
        model = _get_model()
        vectors = model.encode(
            clean_texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=32,
        )
        return [v.tolist() for v in vectors]

    except Exception:
        return [[] for _ in texts]
