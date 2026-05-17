# Stage 36 - Multilingual Normalization Layer

## Status

Completed.

## Stage File

Read: `docs/codex/36_MULTILINGUAL_NORMALIZATION_LAYER.md`.

The file is short/truncated, so the implementation follows the visible stage goal and the user's explicit requirements.

## Scope

Stage 36 added a conservative multilingual normalization layer for search and entity metadata. It does not add database models or migrations, does not replace the Stage 25 alias layer, and does not start Stage 37.

## Implemented

- Added `dms/services/text_normalization.py`.
- Added `NormalizedText` with:
  - `raw_value`
  - `normalized_value`
  - `tokens`
  - `variants`
  - `corrections`
- Added legal form normalization for common business forms:
  - `ip`
  - `too`
  - `ooo`
  - `ao`
- Added latin/cyrillic lookalike variant generation.
- Added conservative OCR correction foundation:
  - corrections are exposed as variants/correction metadata;
  - raw values are not overwritten.
- Added built-in multilingual aliases for common search terms and document types.
- Extended existing `settings.SEARCH_ALIASES` support instead of replacing it.
- Added multilingual query expansion for search embeddings and lexical fallback.
- Added normalization metadata to `Document.search_entities`.
- Added raw/normalized values to extracted entity payloads.
- Updated indexing entity chunks to include normalization variants/corrections.
- Added tests for normalization, legal forms, OCR variants, alias expansion, entity raw/normalized payloads, and document search metadata.

## Important Behavior

- `raw_value` is preserved in normalization payloads and extracted entity payloads.
- `normalized_value` is used for search/query expansion.
- OCR correction is conservative and does not mutate official fields.
- Existing Stage 25 aliases remain supported through `DEFAULT_ALIASES` and `settings.SEARCH_ALIASES`.
- Search scoring uses base query tokens for score denominator while aliases/variants remain available for lexical filtering and expanded embedding text. This avoids weakening text fallback with too many expansion variants.

## Changed Files

- `dms/services/text_normalization.py`
- `dms/services/search_intelligence.py`
- `dms/services/entity_extraction.py`
- `dms/services/document_indexing.py`
- `dms/services/search_experience.py`
- `dms/test_multilingual_normalization_stage36.py`
- `docs/codex/progress/STAGE_36_PROGRESS.md`

## Migrations

None. No schema/model changes were made.

## Checks Run

- `git branch --show-current` - confirmed starting branch.
- `git status --short --branch` - reviewed unrelated docs changes.
- `git fetch --all --prune` - completed.
- `.\.venv\Scripts\python.exe manage.py test dms.test_multilingual_normalization_stage36 --verbosity 2` - passed, 7 tests.
- `.\.venv\Scripts\python.exe manage.py test dms.test_advanced_entity_extraction_stage35 dms.test_search_intelligence_stage25 dms.test_multilingual_normalization_stage36 --verbosity 1` - passed, 19 tests.
- `.\.venv\Scripts\python.exe manage.py test dms.test_search_experience_stage26 dms.test_multilingual_normalization_stage36 --verbosity 1` - passed, 12 tests.
- `.\.venv\Scripts\python.exe manage.py check` - passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` - passed, no changes detected.
- `.\.venv\Scripts\python.exe manage.py migrate --check` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms --verbosity 1` - passed, 183 tests.

## Notes From Full Test Run

The full test suite prints expected warnings for unavailable local Qdrant in resilience/fallback tests, but the suite completes successfully.

## Manual Verification Checklist

- Search for `InVision`, `in vision`, and known Cyrillic/Kazakh variants and confirm the same accessible documents are found.
- Search with legal forms such as `IP`, `TOO`, `T00`, `LLP` and confirm results remain relevant.
- Search OCR-like variants such as `T00 Firma` and confirm canonical variants help matching without changing document fields.
- Confirm document detail/AI review still shows suggestions as suggestions only.
- Reindex a real document and confirm `search_entities.normalization` contains both raw and normalized metadata.
- Confirm organization and object permissions still limit search results.

## Limitations

- This is a conservative rule-based normalization layer, not a full language model or morphology engine.
- OCR corrections are stored as variants and correction hints; they are not aggressive replacements.
- Lookalike and transliteration support is intentionally limited to reduce false positives.

## Stage 37

Not started.
