# Stage 38 Progress - Distributed AI Processing Center

## Status

Completed.

Stage file read: `docs/codex/38_DISTRIBUTED_AI_PROCESSING_CENTER.md`.

Note: the local stage file is truncated after the architectural idea block, so implementation followed the available file text plus the explicit user requirements for ProcessingJob, processing profiles, scheduler, fan-out/fan-in, retry and backpressure.

## Existing processing foundation before Stage 38

- Existing models: `ProcessingJob` and `ExtractedField`.
- `ProcessingJob` was used by the AI review pipeline with `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `REVIEWED` statuses and `UPLOAD` / `MANUAL` sources.
- AI/OCR/embedding calls existed in:
  - `dms/services/document_creation.py` for upload-time text extraction, AI processing and indexing.
  - `dms/services/ai_processing.py` for parser wrapping and editable suggestions.
  - `dms/services/document_indexing.py`, `dms/services/embedding.py`, `dms/services/vector_store.py` for indexing and Qdrant interaction.
  - `dms/management/commands/reindex_search.py` for reindexing.

## Implemented

- Added `ProcessingProfile` for local/global processing configuration:
  - active flag;
  - max concurrent jobs;
  - max attempts;
  - retry backoff;
  - allowed processing stages;
  - safe config JSON with plaintext secret validation.
- Extended `ProcessingJob` with processing-center fields:
  - `profile`;
  - `parent_job`;
  - `pipeline_stage`;
  - `priority`;
  - `attempt_count`;
  - `max_attempts`;
  - `scheduled_at`;
  - `next_retry_at`;
  - `locked_at`;
  - `lock_token`;
  - `idempotency_key`;
  - `center_metadata`.
- Added processing stages:
  - `AI_PARSE`;
  - `OCR`;
  - `TEXT_EXTRACTION`;
  - `ENTITY_EXTRACTION`;
  - `CHUNKING`;
  - `EMBEDDING`;
  - `RERANKING`;
  - `REINDEX`;
  - `FAN_OUT`;
  - `FAN_IN`.
- Added `dms/services/processing_center.py`:
  - default profile creation;
  - safe metadata snapshot without raw file content or server file path;
  - job enqueue with idempotency;
  - backpressure checks;
  - job claiming;
  - retry scheduling;
  - job completion/failure helpers;
  - fan-out/fan-in foundation;
  - queue drain scheduler foundation;
  - local handler registry.
- Added management command:
  - `python manage.py process_ai_queue --limit 10`
  - optional `--organization-id`;
  - optional `--profile-code`.
- Added Django admin support for `ProcessingProfile`.
- Extended `ProcessingJob` admin with stage/profile/retry fields and excluded internal `lock_token` from admin display.
- Added AuditEvent and UsageEvent recording for processing-center lifecycle events where existing services are available.

## Upload/search safety

- Existing upload flow remains synchronous and unchanged.
- Existing AI review flow remains unchanged and compatible because new `ProcessingJob` fields have defaults.
- Existing search/indexing flow remains unchanged.
- The processing center does not write directly to client Qdrant.
- The `REINDEX` handler calls the existing local `index_document()` service.
- No Kubernetes, public API, external GPU center protocol or permanent remote document storage was added.

## Changed files

- `dms/models.py`
- `dms/admin.py`
- `dms/services/processing_center.py`
- `dms/management/commands/process_ai_queue.py`
- `dms/migrations/0037_processing_center_foundation.py`
- `dms/test_processing_center_stage38.py`
- `docs/codex/progress/STAGE_38_PROGRESS.md`

## Migrations

- Added `dms/migrations/0037_processing_center_foundation.py`.
- Local database migrated successfully with `python manage.py migrate`.

## Checks run

- `.\.venv\Scripts\python.exe manage.py makemigrations --name processing_center_foundation dms` - passed.
- `.\.venv\Scripts\python.exe manage.py check` - passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` - passed.
- `.\.venv\Scripts\python.exe manage.py migrate --check` - initially failed before applying the new migration, then passed after `migrate`.
- `.\.venv\Scripts\python.exe manage.py migrate` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms.test_processing_center_stage38 --verbosity 1` - 7 tests passed.
- `.\.venv\Scripts\python.exe manage.py test dms --verbosity 1` - 195 tests passed.

## Manual verification checklist

- In Django admin, verify `ProcessingProfile` records can be viewed and edited without storing plaintext secrets in `config`.
- Create a small processing job with `enqueue_processing_job()` and verify it appears as `PENDING`.
- Run `python manage.py process_ai_queue --limit 1 --organization-id <id>` and verify the job moves to `COMPLETED` or retry state.
- Verify upload still creates a normal `Document`, `DocumentVersion`, AI suggestions and search indexing through the existing flow.
- Verify search still returns organization-scoped results and degrades safely when Qdrant is unavailable.
- Verify no external UI/API exposes `lock_token` or raw client document content.

## Limitations / next-stage notes

- This is a foundation only. No remote GPU-center protocol was added.
- No Kubernetes or public processing API was added.
- Heavy AI/OCR/embedding work is not moved out of upload yet; current upload/search behavior is intentionally preserved.
- Default non-reindex handlers are safe no-op foundation handlers until a real processing backend is connected.
- The local stage file appears truncated, so future stages should confirm any missing Stage 38 requirements before building on this foundation.
