# STAGE 03 PROGRESS

## Stage
Organization / multi-tenancy foundation.

## Branch
stage-03-organization-tenancy

## Current status
Completed and verified locally.

## Scope
- Add Organization and OrganizationMember.
- Attach existing data to Default Organization.
- Make document, department, folder, and document type querysets organization-aware.
- Preserve existing ADMIN / EMPLOYEE roles, department access, DocumentAccess, DocumentActivity, upload flow, and AI extraction.
- Do not start Stage 04.

## Work log
- Created stage branch from `origin/stage-02-core-stabilization`.
- Read `правила/03_ORGANIZATION_TENANCY.md`.
- `docs/codex/03_ORGANIZATION_TENANCY.md` is not present in the repository.
- Added Organization and OrganizationMember models.
- Added organization FKs to Department, Folder, DocumentType, and Document.
- Added migration to attach existing data to Default Organization and create memberships.
- Updated access helpers, forms, views, admin, seed commands, and indexing payload for organization awareness.
- Added tenant isolation tests for allowed documents/departments and upload organization assignment.
- Installed project dependencies into local ignored `.venv` with Python 3.14.
- Started Docker Desktop and a disposable PostgreSQL test container on port `55432` to avoid the existing local PostgreSQL service on port `5432`.
- Added migration `0019_alter_documenttype_options_and_more.py` so Django's migration state matches the current models after Stage 03.

## Checks
- `python manage.py check` passed.
- `python manage.py makemigrations --check --dry-run` passed with no changes detected.
- `python manage.py migrate --noinput` passed on a fresh PostgreSQL test database.
- `python manage.py migrate --check` passed after applying migrations.
- `python manage.py test dms.test_organization_tenancy --noinput` passed: 3 tests.
- `python manage.py test dms --noinput` passed: 36 tests.
- `git diff --check` passed.

## Manual check required
- Run migrations and confirm existing departments, folders, documents, and document types are attached to Default Organization.
- Login as ADMIN and confirm only departments/documents from the member organization are visible.
- Login as EMPLOYEE and confirm own department subtree still works.
- Upload a document as EMPLOYEE and confirm `Document.organization` equals the user's department organization.
- Grant DocumentAccess inside one organization and confirm it does not expose another organization's document.
- Confirm document list/search/detail/view/download still work for existing documents.
