# STAGE 07 PROGRESS

## Stage
Import / Migration Layer.

## Branch
stage-07-import-migration-layer

## Current status
Completed and verified locally.

## Scope
- Add import batches and per-file import tracking.
- Imported files become regular `Document` records.
- Preserve single document upload, `DocumentVersion`, `AuditEvent`, AI Processing Pipeline, ADMIN / EMPLOYEE access, department access, and organization isolation.
- Do not add external integrations, Workflow, Counterparty Portal, B2B Exchange, or Billing.

## Work log
- Created stage branch from completed `stage-06-ai-processing-pipeline`.
- Read `C:\Users\Smart Product\Desktop\dmsv2\правила\07_IMPORT_MIGRATION_LAYER.md`.
- `docs/codex/07_IMPORT_MIGRATION_LAYER.md` is not present in the repository.
- Added `ImportBatch` and `ImportFile` models.
- Added shared document creation service used by single upload and import.
- Added multiple files import form and minimal import UI.
- Added duplicate detection by SHA-256 within the same organization.
- Import creates regular `Document` records, `DocumentVersion #1`, `DocumentActivity`, and `AuditEvent`.
- Import does not start AI processing automatically.
- Added tests for multiple import, duplicate detection, and permission enforcement.

## Checks
- `python manage.py makemigrations --check --dry-run` passed with no changes detected.
- `python manage.py check` passed.
- `python manage.py migrate --noinput` passed on a fresh PostgreSQL test database.
- `python manage.py migrate --check` passed after applying migrations.
- `python manage.py test dms.test_import_migration_layer --noinput` passed: 3 tests.
- `python manage.py test dms.test_import_migration_layer dms.test_ai_processing_pipeline dms.test_audit_events dms.test_document_core_versioning dms.test_organization_tenancy --noinput` passed: 17 tests.
- `python manage.py test dms --noinput` passed: 50 tests.
- `git diff --check` passed.

## Manual check required
- Import several files into an allowed department/folder and confirm regular documents are created.
- Confirm each imported document has `Document.file`, `DocumentVersion #1`, checksum, and upload activity.
- Import a duplicate file and confirm it is marked duplicate without creating another document.
- Confirm import batches/files are visible in Django admin.
- Confirm employees cannot import into departments outside their access scope.
- Confirm AI processing jobs are not created automatically during import.
