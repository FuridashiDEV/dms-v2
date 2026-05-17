# Stage 46 Progress - Enterprise Security & Data Governance

## Status

Completed.

Stage file read: `docs/codex/46_ENTERPRISE_SECURITY_DATA_GOVERNANCE.md`.

Stage 47 was not started.

## Implemented

- Added `SensitiveEntity` model for safe sensitive-entity references:
  - IIN;
  - BIN;
  - phone;
  - email;
  - amount;
  - personal-name foundation;
  - other personal data placeholder.
- Added `RetentionPolicy` model for retention foundation:
  - documents;
  - document versions;
  - audit events;
  - processing results;
  - temporary files.
- Added `dms/services/data_governance.py`:
  - regex-based sensitive entity detection;
  - masked value generation;
  - SHA-256 raw-value hash;
  - safe persistence without raw PII;
  - metadata sanitizer for tokens, secrets, file paths, raw text, payloads and query-like keys;
  - safe AI/processing metadata builder;
  - default review-only retention policy creation.
- Hardened `record_audit_event`:
  - removes raw document title from default audit metadata;
  - stores `document_title_hash` instead;
  - sanitizes metadata before saving.
- Added access/search audit hardening:
  - document detail view audit;
  - protected file view/download audit surfaces;
  - document version view/download audit surfaces;
  - search audit event `DOCUMENT_SEARCHED` without raw query text.
- Added AI privacy foundation:
  - AI processing detects sensitive entities from processing text;
  - persists only masked/hash entity references;
  - audit metadata stores entity counts, not raw text or values.
- Hardened processing center metadata:
  - no document title or organization name in center metadata;
  - optional payload is sanitized into `payload_summary`.
- Added Django admin registration for `SensitiveEntity` and `RetentionPolicy`.
- Added `docs/DATA_GOVERNANCE.md`.
- Added focused Stage 46 tests.

## Security / privacy constraints

- Raw PII is not stored in `SensitiveEntity`.
- Audit metadata is sanitized before storage.
- Raw search query text is not stored in audit events.
- Full document text and extracted text are not stored in processing center metadata.
- File paths, tokens, secrets, passwords, API keys and authorization values are redacted in governance metadata.
- Retention policies are foundation-only and do not automatically delete data.

## Changed files

- `dms/admin.py`
- `dms/models.py`
- `dms/migrations/0042_enterprise_security_data_governance.py`
- `dms/services/ai_processing.py`
- `dms/services/audit.py`
- `dms/services/data_governance.py`
- `dms/services/processing_center.py`
- `dms/views.py`
- `dms/test_enterprise_security_data_governance_stage46.py`
- `docs/DATA_GOVERNANCE.md`
- `docs/codex/progress/STAGE_46_PROGRESS.md`

## Migrations

- Added `dms/migrations/0042_enterprise_security_data_governance.py`.
- Migration adds:
  - `SensitiveEntity`;
  - `RetentionPolicy`;
  - `DOCUMENT_SEARCHED` audit event choice.
- Applied locally with `python manage.py migrate`.

## Checks run

- `git fetch --all --prune` - passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --name enterprise_security_data_governance dms` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms.test_enterprise_security_data_governance_stage46 --verbosity 2` - 7 tests passed.
- `.\.venv\Scripts\python.exe manage.py check` - passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` - passed, no changes detected.
- `.\.venv\Scripts\python.exe manage.py migrate --check` - initially failed because Stage 46 migration was unapplied.
- `.\.venv\Scripts\python.exe manage.py migrate` - passed.
- `.\.venv\Scripts\python.exe manage.py migrate --check` - passed after local migration.
- `.\.venv\Scripts\python.exe manage.py test dms --verbosity 1` - 236 tests passed.
- `git diff --check` - passed with LF/CRLF warnings for touched files.

## Expected test/runtime warnings

- Full suite printed existing expected warnings for negative permission/404 tests.
- Full suite printed expected Qdrant unavailable warnings because local Qdrant is not running.
- Full suite printed an HF Hub unauthenticated warning while loading local embedding dependencies.

## Manual verification checklist

- Open Django admin and confirm `SensitiveEntity` records show masked values only.
- Run AI processing on a synthetic document containing email/IIN/BIN/phone and confirm raw values are not stored in `SensitiveEntity`.
- Search with a sensitive query and confirm `AuditEvent.DOCUMENT_SEARCHED` stores length/result metadata but not the raw query.
- View/download a document and confirm audit metadata has the correct `surface`.
- Confirm processing job `center_metadata` contains no full document text, file path, token or raw payload.
- Create default retention policies with `ensure_default_retention_policies` and confirm they are review-only.
- Review `docs/DATA_GOVERNANCE.md` against pilot data handling requirements before using real regulated documents.

## Limitations / next-stage notes

- Sensitive entity detection is regex/foundation based and not exhaustive.
- Personal-name detection is intentionally conservative.
- Retention policies do not perform deletion or archival automation.
- No claims are made about SOC2, ISO, legal certification or complete PII discovery.
