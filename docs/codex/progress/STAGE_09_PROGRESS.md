# STAGE 09 PROGRESS

## Stage
Counterparty Portal MVP.

## Branch
stage-09-counterparty-portal-mvp

## Current status
Completed and verified locally.

## Scope
- Add a minimal external counterparty portal linked to existing `Document`.
- Preserve upload flow, document list/detail, DocumentVersion, AuditEvent, AI Processing Pipeline, Import Layer, Workflow, ADMIN / EMPLOYEE access, department access, and organization isolation.
- Do not add external user registration, supplier network, e-signature/EDS, Peppol/EDI, Billing, or Stage 10 features.

## Work log
- Created stage branch from completed `stage-08-workflow-engine-mvp`.
- Read `C:\Users\Smart Product\Desktop\dmsv2\правила\09_COUNTERPARTY_PORTAL_MVP.md`.
- `docs/codex/09_COUNTERPARTY_PORTAL_MVP.md` is not present in the repository.
- Started Counterparty Portal MVP design against existing DMS models and permissions.
- Added `Counterparty`, `DocumentExchange`, and `ExchangeEvent` models.
- Added secure token generation with SHA-256 token hash storage.
- Added internal send flow and public token portal views.
- Added focused Stage 09 tests for send, portal open/download/accept/reject/comment, and permission denial.
- Generated migration `0025_alter_auditevent_event_type_counterparty_and_more.py`.
- Full `dms` test suite passes.

## Checks
- `python manage.py makemigrations --check --dry-run` passed with no changes detected.
- `python manage.py check` passed.
- `python manage.py migrate --noinput` passed on a fresh PostgreSQL test database.
- `python manage.py migrate --check` passed after applying migrations.
- `python manage.py test dms.test_counterparty_portal_mvp --noinput` passed: 4 tests.
- `python manage.py test dms.test_counterparty_portal_mvp dms.test_workflow_engine_mvp dms.test_import_migration_layer dms.test_ai_processing_pipeline dms.test_audit_events dms.test_document_core_versioning dms.test_organization_tenancy --noinput` passed: 25 tests.
- `python manage.py test dms --noinput` passed: 58 tests.
- `git diff --check` passed.

## Manual check required
- Create/send a document exchange from document detail.
- Open the external portal token URL without logging in.
- Confirm only the exchanged document is visible.
- Download the document through the portal.
- Accept, reject, and comment from the portal.
- Confirm `ExchangeEvent` and `AuditEvent` records are written.
- Confirm internal users without document access cannot create exchanges.
