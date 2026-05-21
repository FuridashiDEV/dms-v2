# Stage 50 - Model Stack Stabilization Progress

## Scope

Stabilized the model stack foundation for DocFlow search without blindly replacing the current embedding model and without changing upload/search permissions or Qdrant collection data.

## Baseline model

- Current configured embedding model: `BAAI/bge-m3`.
- Baseline fallback candidate: `all-MiniLM-L6-v2`.
- Current default reranker: `noop`.

## Tested model candidates

- `BAAI/bge-m3`
- `intfloat/multilingual-e5-large`
- `all-MiniLM-L6-v2`
- Optional reranker candidate: `BAAI/bge-reranker-v2-m3`
- Safe reranker fallback: `noop`

## Vector dimensions

- `BAAI/bge-m3`: 1024
- `intfloat/multilingual-e5-large`: 1024
- `all-MiniLM-L6-v2`: 384

Vector dimension validation now rejects empty vectors and dimension mismatches before Qdrant upsert.

## Qdrant compatibility

- One Qdrant collection remains tied to one embedding model/dimension through `SearchIndexVersion`.
- Recommended collection names are model-specific:
  - `documents_baai_bge_m3`
  - `documents_intfloat_multilingual_e5_large`
  - `documents_all_minilm_l6_v2`
- The implementation does not delete Qdrant collections and does not mix embedding dimensions.

## SearchIndexVersion behavior

`get_active_search_index_version()` continues to create or reuse an active version based on:

- embedding model
- embedding dimension
- chunking version
- normalization version
- Qdrant collection

It continues to reject active collection conflicts across different model/dimension pairs.

## DocumentSearchIndexState behavior

No schema changes were made. `DocumentSearchIndexState` continues to track:

- organization
- document
- document version
- search index version
- status
- content hash
- Qdrant point IDs
- collection name

## Reranker behavior

- Added `RerankerAdapter` foundation.
- Added `BgeRerankerV2M3Adapter` for optional `BAAI/bge-reranker-v2-m3`.
- Added `NoOpRerankerAdapter` as the default safe fallback.
- Existing search ranking keeps working without model reranking.
- Reranker loading is optional and disabled by default.

## E5 prefix behavior

`intfloat/multilingual-e5-large` uses:

- query prefix: `query: `
- passage/document prefix: `passage: `

The prefix handling lives inside `MultilingualE5LargeEmbeddingAdapter`, so callers do not need to duplicate E5-specific logic.

## Entity extraction / normalization / explanation

- Entity extraction remains deterministic and rules-based.
- Sensitive entity handling was not loosened.
- Normalization and aliases remain deterministic.
- Explanation remains based on actual search signals; no free-form LLM explanations were added.
- Raw Qdrant payloads, tokens and inaccessible documents are not exposed.

## Benchmark results

Command:

`.\.venv\Scripts\python.exe manage.py benchmark_model_stack --dataset synthetic --limit 50 --format json`

Latest local synthetic benchmark:

- dataset: `synthetic`
- embedding model: `BAAI/bge-m3`
- vector dimension: 1024
- reranker: `noop`
- top-1 accuracy: 1.00
- top-3 accuracy: 1.00
- top-5 accuracy: 1.00
- MRR: 1.00
- precision@5: 0.20
- recall@10: 1.00
- average latency: 26.1681 ms
- p95 latency: 29.0031 ms
- embedding time per document: 0.4836 ms in safe fallback mode
- reranking latency: 0.0079 ms with noop reranker
- Qdrant insert time: 0 ms because the default benchmark does not write to Qdrant
- fallback count: 7 because default benchmark mode avoids heavy model loading unless `--load-models` is passed

## Recommendation

Keep `BAAI/bge-m3` as the configured default for now. It is the right primary candidate for multilingual RU/KZ/EN search, but production model replacement decisions should wait for real document benchmarks with `--load-models` and a disposable or explicitly selected benchmark collection.

Do not enable `BAAI/bge-reranker-v2-m3` by default until latency and memory are measured on the target environment.

## Limitations

- Synthetic benchmark does not prove production accuracy.
- Default benchmark mode intentionally avoids downloading/loading heavy models.
- Qdrant insert timing is reported as `0` unless the benchmark is extended to write to a disposable collection.
- OCR quality for Russian/Kazakh remains tied to the existing OCR/text extraction layer and should be evaluated on real scanned documents.
- No claims of 99-100% accuracy are made.

## Checks

- `.\.venv\Scripts\python.exe manage.py check` - passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` - passed, no changes detected.
- `.\.venv\Scripts\python.exe manage.py migrate --check` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms --verbosity 1` - passed, 258 tests OK.
- `.\.venv\Scripts\python.exe manage.py benchmark_model_stack --dataset synthetic --limit 50 --format json` - passed.
- `git diff --check` - passed; only LF/CRLF warnings were reported.
- `git status` - checked; unrelated pre-existing local changes remain outside the Stage 50 commit.

## Intentionally not changed

- No unrestricted autonomous agents were added.
- The current search flow was not rewritten.
- Upload flow was not changed.
- Permissions and organization isolation were not changed.
- Existing Qdrant collections are not deleted.
- Embeddings from different models are not mixed in one collection.
- No migrations were added.
