# AI and Search Architecture

DocFlow uses AI as an assistive layer, not as an unrestricted autonomous agent.

## Layers

- Text extraction/OCR foundation.
- Entity extraction for document type, counterparty, amount, date, document number and subject.
- Normalization and alias expansion for Russian/Kazakh/mixed-language terms.
- Embedding adapters for `BAAI/bge-m3`, `intfloat/multilingual-e5-large` and baseline fallback.
- Qdrant vector store with one collection per embedding model.
- Reranking foundation with optional BGE reranker and safe noop fallback.
- Deterministic explanations based on actual search signals.

## Safety rules

- AI suggestions do not automatically overwrite official document fields.
- Technical payloads, Qdrant internals, point IDs, chunk IDs and raw scores are not shown to regular users.
- Search results and related documents must pass organization and object-level permission checks.

## Benchmark status

The repository includes synthetic and semi-real benchmark datasets. They support top-k, MRR, precision/recall and latency checks. Results are not marketed as production accuracy guarantees.
