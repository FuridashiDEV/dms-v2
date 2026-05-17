# Stage 40 Progress - Incremental Indexing & Vector Versioning

## Status

Completed.

Stage file read: `docs/codex/40_INCREMENTAL_INDEXING_VECTOR_VERSIONING.md`.

Note: the local stage file is truncated after the stable chunk id section, so implementation followed the available file text and explicit user requirements.

## Implemented

- Added `SearchIndexVersion`:
  - `embedding_model`;
  - `embedding_dimension`;
  - `chunking_version`;
  - `normalization_version`;
  - `qdrant_collection`;
  - `is_active`;
  - `created_at`.
- Added `DocumentSearchIndexState`:
  - `document`;
  - `document_version`;
  - `index_version`;
  - `status`;
  - `indexed_at`;
  - `chunks_count`;
  - `qdrant_collection`;
  - `content_hash`;
  - `point_ids`;
  - `last_error`.
- Added version/stale service in `dms/services/index_versions.py`.
- Added stable point IDs using:
  - Qdrant collection;
  - document id;
  - document version id;
  - chunk key;
  - search index version id.
- Updated `index_document()` to:
  - create/get active index version;
  - record document index state;
  - detect and store content fingerprint;
  - upsert current points first;
  - cleanup only known stale point IDs after successful upsert;
  - record failed state when vectors/upsert fail.
- Added `delete_points()` to Qdrant vector store for safe point-level cleanup.
- Updated `reindex_search --only-stale` to use `DocumentSearchIndexState` and fingerprint stale detection instead of only checking `search_indexed_at IS NULL`.
- Added settings/env defaults:
  - `SEARCH_CHUNKING_VERSION`;
  - `SEARCH_NORMALIZATION_VERSION`.
- Added Django admin for `SearchIndexVersion` and `DocumentSearchIndexState`.
- Updated existing Stage 25 indexing test to assert versioned payload instead of pre-upsert document deletion.

## Safety rules

- No full Qdrant collection delete was added.
- `index_document()` no longer deletes all document points before upsert.
- Cleanup is point-level and only uses stored stale point IDs.
- Active index version validation prevents one Qdrant collection from mixing active embedding models/dimensions.
- Existing `Document.search_*` fields remain for backwards compatibility.
- Search, upload, import, processing center and Kubernetes foundation flows were not replaced.
- Stage 41 was not started.

## Changed files

- `.env.example`
- `config/settings.py`
- `dms/admin.py`
- `dms/models.py`
- `dms/migrations/0038_incremental_indexing_vector_versioning.py`
- `dms/services/document_indexing.py`
- `dms/services/index_versions.py`
- `dms/services/vector_store.py`
- `dms/management/commands/reindex_search.py`
- `dms/test_incremental_indexing_stage40.py`
- `dms/test_search_intelligence_stage25.py`
- `docs/codex/progress/STAGE_40_PROGRESS.md`

## Migrations

- Added `dms/migrations/0038_incremental_indexing_vector_versioning.py`.
- Applied locally with `python manage.py migrate`.

## Checks run

- `.\.venv\Scripts\python.exe manage.py makemigrations --name incremental_indexing_vector_versioning dms` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms.test_incremental_indexing_stage40 dms.test_search_intelligence_stage25.SearchIndexingTests --verbosity 1` - 8 tests passed after one stale-hash ordering fix.
- `.\.venv\Scripts\python.exe manage.py check` - passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` - passed.
- `.\.venv\Scripts\python.exe manage.py migrate --check` - initially failed before applying the new migration, then passed after `migrate`.
- `.\.venv\Scripts\python.exe manage.py migrate` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms --verbosity 1` - 206 tests passed.

## Manual verification checklist

- In admin, confirm `SearchIndexVersion` is created for the configured embedding model/dimension/collection.
- Upload or edit a document and verify `DocumentSearchIndexState` becomes `INDEXED`.
- Change document text/metadata and verify `is_document_index_stale(document)` returns true before reindex.
- Run `python manage.py reindex_search --only-stale --limit 10` and verify only stale/missing states are processed.
- Verify Qdrant points include `document_version_id`, `search_index_version_id`, `chunk_key`, `embedding_model` and organization payload fields.
- Verify Qdrant cleanup deletes only stored stale point IDs, not the entire collection.
- Before changing embedding dimension/model in production, change Qdrant collection name or create a separate collection.

## Limitations / next-stage notes

- Historical documents will get `DocumentSearchIndexState` on their next reindex; no bulk backfill was forced automatically.
- The safe cleanup mechanism depends on stored `point_ids`; points created before Stage 40 may need one controlled reindex cycle before they are fully represented in state.
- KEDA/worker orchestration from Stage 39 can call the same `reindex_search` and processing role commands, but Stage 40 does not add new Kubernetes resources.
