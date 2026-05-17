# Stage 37 - Advanced Reranking Pipeline

## Status

Completed.

## Stage File

Read: `docs/codex/37_ADVANCED_RERANKING_PIPELINE.md`.

## Scope

Stage 37 added a search reranking foundation without rewriting Stage 25-26 search, without making model reranking mandatory, and without requiring Qdrant. Existing lexical, semantic fallback, alias, entity, permission, and organization isolation behavior remains in place.

## Implemented

- Added `dms/services/reranking.py`.
- Added candidate fusion across multiple candidate sources:
  - exact candidates;
  - structured entity candidates;
  - text candidates;
  - alias candidates;
  - vector candidates;
  - related-document candidates.
- Added source-weighted fusion scoring.
- Added final scoring that preserves the existing base search score and adds fusion/reranker contributions.
- Added confidence scoring based on final score, source diversity, and explanation coverage.
- Added explanation reasons with candidate sources, retrieval signals, base match reasons, optional reranker reasons, final score, and confidence.
- Added optional reranker hook foundation. If no reranker is configured, search continues with deterministic scoring.
- Integrated reranking into `document_list` after existing candidate retrieval and access-filtered queryset construction.
- Added related-document candidates with final permission checks through `base_qs`.
- Added focused tests for fusion, final score, confidence, optional reranker behavior, semantic fallback without Qdrant, and related candidate handling.

## Important Behavior

- Qdrant remains optional. If embeddings/vector search are unavailable, semantic mode degrades to safe text results.
- Model reranker is optional. The service accepts a reranker hook but does not require or load any external model.
- Final scoring never lowers the existing base score below the previous search threshold behavior.
- Related document candidates are filtered through the already permission-scoped queryset before ranking.
- Result documents now receive:
  - `search_explanation`
  - `search_confidence`
  - `search_final_score`
  - `search_candidate_sources`

## Changed Files

- `dms/services/reranking.py`
- `dms/views.py`
- `dms/test_advanced_reranking_stage37.py`
- `docs/codex/progress/STAGE_37_PROGRESS.md`

## Migrations

None. No model/schema changes were made.

## Checks Run

- `git branch --show-current` - confirmed starting branch.
- `git status --short --branch` - reviewed unrelated docs changes.
- `git fetch --all --prune` - completed.
- `.\.venv\Scripts\python.exe manage.py test dms.test_advanced_reranking_stage37 --verbosity 2` - passed, 5 tests.
- `.\.venv\Scripts\python.exe manage.py test dms.test_search_experience_stage26 dms.test_enterprise_search_quality_stage34 dms.test_multilingual_normalization_stage36 --verbosity 1` - passed, 17 tests.
- `.\.venv\Scripts\python.exe manage.py check` - passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` - passed, no changes detected.
- `.\.venv\Scripts\python.exe manage.py migrate --check` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms --verbosity 1` - passed, 188 tests.

## Notes From Full Test Run

The full test suite prints expected warnings for unavailable local Qdrant in resilience/fallback tests, but the suite completes successfully.

## Manual Verification Checklist

- Search by exact title and confirm exact/entity matches rank above weaker semantic-only matches.
- Search by alias/normalized query and confirm relevant documents still appear.
- Run semantic mode while Qdrant is unavailable and confirm text fallback works.
- Confirm explanations show candidate sources and final score/confidence.
- Confirm related documents appear only when the user has access.
- Confirm documents from another organization or restricted department are not surfaced.

## Limitations

- This stage adds deterministic reranking foundation, not a production ML cross-encoder reranker.
- Optional reranker hooks are prepared but no external reranker model is loaded or required.
- Fusion weights are conservative defaults and should be tuned with real search evaluation data.

## Stage 38

Not started.
