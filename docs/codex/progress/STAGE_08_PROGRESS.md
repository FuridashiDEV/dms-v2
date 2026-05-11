# STAGE 08 PROGRESS

## Stage
Workflow Engine MVP.

## Branch
stage-08-workflow-engine-mvp

## Current status
Completed and verified locally.

## Scope
- Add workflow models linked to existing `Document`.
- Add simple approval service and document status transitions.
- Preserve upload flow, document list/detail, DocumentVersion, AuditEvent, AI Processing Pipeline, Import Layer, ADMIN / EMPLOYEE access, department access, and organization isolation.
- Do not add Counterparty Portal, B2B Exchange, Legal Evidence Export, Billing, or BPMN/no-code workflow builder.

## Work log
- Created stage branch from completed `stage-07-import-migration-layer`.
- Read `C:\Users\Smart Product\Desktop\dmsv2\правила\08_WORKFLOW_ENGINE_MVP.md`.
- `docs/codex/08_WORKFLOW_ENGINE_MVP.md` is not present in the repository.
- Started workflow model, service, view, URL, and detail UI implementation.
- Added focused Stage 08 tests for start, approve, permission denial, and request changes.
- Generated migration `0024_alter_auditevent_event_type_alter_document_status_and_more.py`.
- Fixed PostgreSQL `select_for_update` locking for nullable workflow step joins.
- Full `dms` test suite passes.

## Checks
- `python manage.py makemigrations --check --dry-run` passed with no changes detected.
- `python manage.py check` passed.
- `python manage.py migrate --noinput` passed on a fresh PostgreSQL test database.
- `python manage.py migrate --check` passed after applying migrations.
- `python manage.py test dms.test_workflow_engine_mvp --noinput` passed: 4 tests.
- `python manage.py test dms.test_workflow_engine_mvp dms.test_import_migration_layer dms.test_ai_processing_pipeline dms.test_audit_events dms.test_document_core_versioning dms.test_organization_tenancy --noinput` passed: 21 tests.
- `python manage.py test dms --noinput` passed: 54 tests.
- `git diff --check` passed.

## Manual check required
- Create a workflow template and step in Django admin.
- Start workflow from a document detail page.
- Confirm document status changes to `IN_REVIEW`.
- Approve final step and confirm document status changes to `APPROVED`.
- Reject and request changes flows should set `REJECTED` / `CHANGES_REQUESTED`.
- Confirm only assigned approver/admin can act.
- Confirm `WorkflowAction`, `DocumentActivity`, `DocumentVersion`, and `AuditEvent` records are created.
