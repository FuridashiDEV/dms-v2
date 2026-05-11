# STAGE 05 PROGRESS

## Stage
AuditEvent: system audit trail.

## Branch
stage-05-audit-events

## Current status
Completed and verified locally.

## Scope
- Add system audit events connected to current DMS documents.
- Preserve `DocumentActivity` for dashboard/recent activity.
- Preserve upload flow, `DocumentVersion`, ADMIN / EMPLOYEE access, department access, and organization isolation.
- Do not add AI Processing models, Workflow, Counterparty Portal, B2B Exchange, or Legal Evidence export.

## Work log
- Created stage branch from completed `stage-04-document-core-versioning`.
- Read `C:\Users\Smart Product\Desktop\dmsv2\правила\05_AUDIT_EVENTS.md`.
- `docs/codex/05_AUDIT_EVENTS.md` is not present in the repository.
- Added `AuditEvent` model for system/security audit trail.
- Added `dms.services.audit.record_audit_event` with request IP/user-agent helpers.
- Added audit calls to document upload, edit, view, download, version view/download, access grant/revoke, status change, and delete flows.
- Kept all existing `DocumentActivity` writes.
- Added Django admin for `AuditEvent`.
- Added tests for audit service metadata, upload audit, view/download audit, access audit, and delete snapshot behavior.

## Checks
- `python manage.py makemigrations --check --dry-run` passed with no changes detected.
- `python manage.py check` passed.
- `python manage.py migrate --noinput` passed on a fresh PostgreSQL test database.
- `python manage.py migrate --check` passed after applying migrations.
- `python manage.py test dms.test_audit_events dms.test_document_core_versioning dms.test_organization_tenancy --noinput` passed: 11 tests.
- `python manage.py test dms --noinput` passed: 44 tests.
- `git diff --check` passed.

## Manual check required
- Upload a document and confirm both `DocumentActivity` and `AuditEvent` are created.
- View/download document and document version; confirm audit rows include user, organization, document/version, IP, and user-agent.
- Grant/revoke document access and confirm audit metadata includes department ids.
- Delete a document and confirm audit row remains with metadata snapshot after document FK becomes null.
- Confirm users from another organization cannot create audit events for inaccessible documents through current views.
