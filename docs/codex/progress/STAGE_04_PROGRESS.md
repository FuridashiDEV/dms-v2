# STAGE 04 PROGRESS

## Stage
Document Core 2.0: versions, statuses, hash.

## Branch
stage-04-document-core-versioning

## Current status
Completed and verified locally.

## Scope
- Preserve existing `Document.file`, upload flow, document list/detail, ADMIN / EMPLOYEE access, department access, and organization isolation.
- Keep existing AI extraction and metadata parsing behavior.
- Do not add AuditEvent, AI Processing models, Workflow, Counterparty Portal, or B2B Exchange.

## Work log
- Created stage branch from completed `stage-03-organization-tenancy`.
- Read `C:\Users\Smart Product\Desktop\dmsv2\правила\04_DOCUMENT_CORE_VERSIONING.md`.
- `docs/codex/04_DOCUMENT_CORE_VERSIONING.md` is not present in the repository.
- Found that `Document.status`, `Document.checksum_sha256`, `DocumentVersion`, version routes, and current upload version creation already exist in the codebase.
- Added `DocumentVersion.organization` so version snapshots are explicitly tenant-aware.
- Added a safe migration to attach existing versions to their document organization and create missing v1 snapshots for legacy documents that still have `Document.file`.
- Added `calculate_file_sha256` for Django uploaded files / FieldFile objects while keeping the existing path-based helper.
- Updated upload metadata population so checksum is calculated before `DocumentVersion #1` is created.
- Added tests for SHA-256 helper, upload-created v1 snapshots, tenant-aware versions, and legacy snapshot checksum fallback.

## Checks
- `python manage.py makemigrations --check --dry-run` passed with no changes detected.
- `python manage.py check` passed.
- `python manage.py migrate --noinput` passed on a fresh PostgreSQL test database.
- `python manage.py migrate --check` passed after applying migrations.
- `python manage.py test dms.test_document_core_versioning dms.test_organization_tenancy --noinput` passed: 6 tests.
- `python manage.py test dms --noinput` passed: 39 tests.
- `git diff --check` passed.

## Manual check required
- Apply migrations and confirm existing `DocumentVersion` rows receive the same organization as their parent document.
- Confirm documents with `Document.file` and no versions receive `DocumentVersion #1`.
- Upload a new document and confirm `Document.file` still works, `DocumentVersion #1` is created, and checksums match.
- Open document list/detail/view/download as ADMIN and EMPLOYEE.
- Confirm another organization cannot access document versions through detail/view/download URLs.
