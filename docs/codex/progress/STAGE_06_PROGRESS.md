# STAGE 06 PROGRESS

## Stage
AI Processing Pipeline and manual validation.

## Branch
stage-06-ai-processing-pipeline

## Current status
Completed and verified locally.

## Scope
- Add managed AI processing around the current parser.
- Store AI output as editable suggestions.
- Apply AI output to `Document` only after human confirmation.
- Preserve upload flow, document list/detail, `DocumentVersion`, `AuditEvent`, ADMIN / EMPLOYEE access, department access, and organization isolation.
- Do not add Workflow, Counterparty Portal, B2B Exchange, or Legal Evidence export.

## Work log
- Created stage branch from completed `stage-05-audit-events`.
- Read `C:\Users\Smart Product\Desktop\dmsv2\правила\06_AI_PROCESSING_PIPELINE.md`.
- `docs/codex/06_AI_PROCESSING_PIPELINE.md` is not present in the repository.
- Added `ProcessingJob` and `ExtractedField` models.
- Added managed AI service wrapping the existing `parse_document` parser.
- Changed upload AI behavior so parser output is saved as suggestions and is not applied directly to `Document`.
- Added AI review page for editing, confirming, rejecting, and applying confirmed fields.
- Added AuditEvent types/calls for AI processing and validation.
- Added tests for suggestion storage, manual validation/apply, and access protection.

## Checks
- `python manage.py makemigrations --check --dry-run` passed with no changes detected.
- `python manage.py check` passed.
- `python manage.py migrate --noinput` passed on a fresh PostgreSQL test database.
- `python manage.py migrate --check` passed after applying migrations.
- `python manage.py test dms.test_ai_processing_pipeline --noinput` passed: 3 tests.
- `python manage.py test dms.test_ai_processing_pipeline dms.test_audit_events dms.test_document_core_versioning dms.test_organization_tenancy --noinput` passed: 14 tests.
- `python manage.py test dms --noinput` passed: 47 tests.
- `git diff --check` passed.

## Manual check required
- Upload a document and confirm AI suggestions are created without changing `Document` fields automatically.
- Open document detail and use the AI review link.
- Edit, confirm, reject, and apply fields; confirm only confirmed fields update the document.
- Confirm applying AI fields creates a new `DocumentVersion`.
- Confirm AI processing and validation writes `AuditEvent` rows.
- Confirm users outside allowed department/organization cannot review AI fields.
