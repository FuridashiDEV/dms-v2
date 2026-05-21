from __future__ import annotations

import hashlib
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from django.conf import settings


BASELINE_MODEL = "all-MiniLM-L6-v2"
BGE_M3_MODEL = "BAAI/bge-m3"
MULTILINGUAL_E5_LARGE_MODEL = "intfloat/multilingual-e5-large"
BGE_RERANKER_V2_M3_MODEL = "BAAI/bge-reranker-v2-m3"
NOOP_RERANKER_MODEL = "noop"


@dataclass(frozen=True)
class EmbeddingModelSpec:
    name: str
    dimension: int
    adapter: str
    query_prefix: str = ""
    passage_prefix: str = ""
    recommended_collection_suffix: str = ""
    notes: str = ""


@dataclass(frozen=True)
class RerankerModelSpec:
    name: str
    adapter: str
    optional: bool = True
    notes: str = ""


@dataclass(frozen=True)
class VectorValidationResult:
    valid: bool
    expected_dimension: int
    actual_dimension: int
    model_name: str
    reason: str = ""


@dataclass(frozen=True)
class RerankResult:
    index: int
    score: float
    reason: str = ""


EMBEDDING_MODEL_REGISTRY: dict[str, EmbeddingModelSpec] = {
    BGE_M3_MODEL: EmbeddingModelSpec(
        name=BGE_M3_MODEL,
        dimension=1024,
        adapter="bge-m3",
        recommended_collection_suffix="baai_bge_m3",
        notes="Primary multilingual candidate for RU/KZ/EN business search.",
    ),
    MULTILINGUAL_E5_LARGE_MODEL: EmbeddingModelSpec(
        name=MULTILINGUAL_E5_LARGE_MODEL,
        dimension=1024,
        adapter="multilingual-e5-large",
        query_prefix="query: ",
        passage_prefix="passage: ",
        recommended_collection_suffix="intfloat_multilingual_e5_large",
        notes="Strong multilingual candidate; requires E5 query/passage prefixes.",
    ),
    BASELINE_MODEL: EmbeddingModelSpec(
        name=BASELINE_MODEL,
        dimension=384,
        adapter="baseline",
        recommended_collection_suffix="all_minilm_l6_v2",
        notes="Small baseline fallback; faster and lighter but weaker for RU/KZ semantic quality.",
    ),
}

RERANKER_MODEL_REGISTRY: dict[str, RerankerModelSpec] = {
    BGE_RERANKER_V2_M3_MODEL: RerankerModelSpec(
        name=BGE_RERANKER_V2_M3_MODEL,
        adapter="bge-reranker-v2-m3",
        optional=True,
        notes="Optional cross-encoder reranker for top-k candidates.",
    ),
    NOOP_RERANKER_MODEL: RerankerModelSpec(
        name=NOOP_RERANKER_MODEL,
        adapter="noop",
        optional=True,
        notes="Safe fallback; preserves existing deterministic ranking.",
    ),
}

_MODEL_CACHE: dict[str, object] = {}
_MODEL_LOCK = threading.Lock()


class EmbeddingModelAdapter:
    spec: EmbeddingModelSpec

    def __init__(self, spec: EmbeddingModelSpec):
        self.spec = spec

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def dimension(self) -> int:
        return self.spec.dimension

    def prepare_query(self, text: str) -> str:
        return self._prepare_text(text, prefix=self.spec.query_prefix)

    def prepare_passage(self, text: str) -> str:
        return self._prepare_text(text, prefix=self.spec.passage_prefix)

    def encode_query(self, text: str) -> list[float]:
        return self._encode_one(self.prepare_query(text))

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        prepared = [self.prepare_passage(text) for text in texts]
        return self._encode_many(prepared)

    def validate_vector(self, vector: Sequence[float] | None) -> VectorValidationResult:
        return validate_embedding_vector(vector, model_name=self.name, expected_dimension=self.dimension)

    def _prepare_text(self, text: str, *, prefix: str = "") -> str:
        value = (text or "").strip()
        if not value:
            return ""
        max_chars = int(getattr(settings, "SEARCH_EMBEDDING_MAX_CHARS", 8000) or 8000)
        value = value[:max_chars]
        return f"{prefix}{value}" if prefix and not value.startswith(prefix) else value

    def _get_sentence_transformer(self):
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # pragma: no cover - depends on optional runtime package
            raise RuntimeError("sentence-transformers is not available") from exc

        cache_key = f"embedding:{self.name}"
        model = _MODEL_CACHE.get(cache_key)
        if model is None:
            with _MODEL_LOCK:
                model = _MODEL_CACHE.get(cache_key)
                if model is None:
                    model = SentenceTransformer(self.name)
                    _MODEL_CACHE[cache_key] = model
        return model

    def _encode_one(self, prepared_text: str) -> list[float]:
        if not prepared_text:
            return []
        try:
            model = self._get_sentence_transformer()
            vector = model.encode(
                prepared_text,
                normalize_embeddings=True,
                show_progress_bar=False,
            ).tolist()
        except Exception:
            return []
        validation = self.validate_vector(vector)
        return vector if validation.valid else []

    def _encode_many(self, prepared_texts: Sequence[str]) -> list[list[float]]:
        if not prepared_texts:
            return []
        try:
            model = self._get_sentence_transformer()
            vectors = model.encode(
                list(prepared_texts),
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=int(getattr(settings, "SEARCH_EMBEDDING_BATCH_SIZE", 32) or 32),
            )
        except Exception:
            return [[] for _ in prepared_texts]

        results: list[list[float]] = []
        for vector in vectors:
            values = vector.tolist()
            validation = self.validate_vector(values)
            results.append(values if validation.valid else [])
        return results


class BgeM3EmbeddingAdapter(EmbeddingModelAdapter):
    pass


class MultilingualE5LargeEmbeddingAdapter(EmbeddingModelAdapter):
    pass


class BaselineEmbeddingAdapter(EmbeddingModelAdapter):
    pass


class RerankerAdapter:
    spec: RerankerModelSpec

    def __init__(self, spec: RerankerModelSpec):
        self.spec = spec

    @property
    def name(self) -> str:
        return self.spec.name

    def rerank(self, *, query: str, passages: Sequence[str], top_k: int | None = None) -> list[RerankResult]:
        del query
        limit = len(passages) if top_k is None else max(min(int(top_k or 0), len(passages)), 0)
        return [RerankResult(index=index, score=0.0, reason="noop reranker") for index in range(limit)]


class NoOpRerankerAdapter(RerankerAdapter):
    pass


class BgeRerankerV2M3Adapter(RerankerAdapter):
    def rerank(self, *, query: str, passages: Sequence[str], top_k: int | None = None) -> list[RerankResult]:
        query = (query or "").strip()
        if not query or not passages:
            return []
        started = time.perf_counter()
        try:
            model = self._get_cross_encoder()
            pairs = [(query, passage or "") for passage in passages]
            raw_scores = model.predict(pairs)
        except Exception:
            return [
                RerankResult(index=index, score=0.0, reason="optional reranker unavailable")
                for index in range(min(top_k or len(passages), len(passages)))
            ]
        scored = [
            RerankResult(index=index, score=_sigmoid(float(score)), reason="bge reranker score")
            for index, score in enumerate(raw_scores)
        ]
        scored.sort(key=lambda item: item.score, reverse=True)
        limit = min(top_k or len(scored), len(scored))
        elapsed_ms = (time.perf_counter() - started) * 1000
        return [
            RerankResult(index=item.index, score=item.score, reason=f"bge reranker latency {elapsed_ms:.1f}ms")
            for item in scored[:limit]
        ]

    def _get_cross_encoder(self):
        try:
            from sentence_transformers import CrossEncoder
        except Exception as exc:  # pragma: no cover - depends on optional runtime package
            raise RuntimeError("sentence-transformers CrossEncoder is not available") from exc
        cache_key = f"reranker:{self.name}"
        model = _MODEL_CACHE.get(cache_key)
        if model is None:
            with _MODEL_LOCK:
                model = _MODEL_CACHE.get(cache_key)
                if model is None:
                    model = CrossEncoder(self.name)
                    _MODEL_CACHE[cache_key] = model
        return model


def get_embedding_model_spec(model_name: str | None = None) -> EmbeddingModelSpec:
    name = model_name or getattr(settings, "SEARCH_EMBEDDING_MODEL", BGE_M3_MODEL)
    spec = EMBEDDING_MODEL_REGISTRY.get(name)
    if spec is not None:
        return spec
    dimension = int(getattr(settings, "SEARCH_EMBEDDING_VECTOR_SIZE", 384) or 384)
    return EmbeddingModelSpec(
        name=name,
        dimension=dimension,
        adapter="custom",
        recommended_collection_suffix=_collection_suffix(name),
        notes="Custom embedding model; dimension must be configured explicitly.",
    )


def get_embedding_adapter(model_name: str | None = None) -> EmbeddingModelAdapter:
    spec = get_embedding_model_spec(model_name)
    if spec.name == BGE_M3_MODEL:
        return BgeM3EmbeddingAdapter(spec)
    if spec.name == MULTILINGUAL_E5_LARGE_MODEL:
        return MultilingualE5LargeEmbeddingAdapter(spec)
    if spec.name == BASELINE_MODEL:
        return BaselineEmbeddingAdapter(spec)
    return EmbeddingModelAdapter(spec)


def get_reranker_model_spec(model_name: str | None = None) -> RerankerModelSpec:
    name = model_name or getattr(settings, "SEARCH_RERANKER_MODEL", NOOP_RERANKER_MODEL)
    return RERANKER_MODEL_REGISTRY.get(
        name,
        RerankerModelSpec(name=name, adapter="custom", optional=True, notes="Custom optional reranker."),
    )


def get_reranker_adapter(model_name: str | None = None) -> RerankerAdapter:
    spec = get_reranker_model_spec(model_name)
    if spec.name == BGE_RERANKER_V2_M3_MODEL:
        return BgeRerankerV2M3Adapter(spec)
    return NoOpRerankerAdapter(spec)


def expected_embedding_dimension(model_name: str | None = None) -> int:
    return get_embedding_model_spec(model_name).dimension


def validate_embedding_vector(
    vector: Sequence[float] | None,
    *,
    model_name: str | None = None,
    expected_dimension: int | None = None,
) -> VectorValidationResult:
    spec = get_embedding_model_spec(model_name)
    expected = int(expected_dimension or spec.dimension or 0)
    actual = len(vector or [])
    if not vector:
        return VectorValidationResult(False, expected, actual, spec.name, "empty_vector")
    if expected and actual != expected:
        return VectorValidationResult(False, expected, actual, spec.name, "dimension_mismatch")
    return VectorValidationResult(True, expected, actual, spec.name)


def collection_name_for_model(model_name: str | None = None, *, base: str | None = None) -> str:
    spec = get_embedding_model_spec(model_name)
    collection_base = base or getattr(settings, "SEARCH_QDRANT_COLLECTION_BASE", "documents")
    suffix = spec.recommended_collection_suffix or _collection_suffix(spec.name)
    return f"{collection_base}_{suffix}"


def stable_synthetic_embedding(text: str, *, dimension: int) -> list[float]:
    """Deterministic local fallback for benchmarks that must not download models."""
    if dimension <= 0:
        return []
    seed = hashlib.sha256((text or "").encode("utf-8")).digest()
    values = []
    counter = 0
    while len(values) < dimension:
        digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        values.extend(((byte / 127.5) - 1.0) for byte in digest)
        counter += 1
    vector = values[:dimension]
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [round(value / norm, 8) for value in vector]


def registry_snapshot() -> dict:
    return {
        "embeddings": {
            name: {
                "dimension": spec.dimension,
                "adapter": spec.adapter,
                "query_prefix": spec.query_prefix,
                "passage_prefix": spec.passage_prefix,
                "recommended_collection": collection_name_for_model(name),
                "notes": spec.notes,
            }
            for name, spec in EMBEDDING_MODEL_REGISTRY.items()
        },
        "rerankers": {
            name: {
                "adapter": spec.adapter,
                "optional": spec.optional,
                "notes": spec.notes,
            }
            for name, spec in RERANKER_MODEL_REGISTRY.items()
        },
    }


def _collection_suffix(model_name: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in model_name.lower()).strip("_")


def _sigmoid(value: float) -> float:
    try:
        return round(1 / (1 + math.exp(-value)), 4)
    except OverflowError:
        return 1.0 if value > 0 else 0.0
