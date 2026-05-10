# STAGE 03 PROGRESS

## Stage
Organization / multi-tenancy foundation.

## Branch
stage-03-organization-tenancy

## Current status
Completed with environment check caveat: Django is not installed in the local Python environment, so Django system checks/tests could not run here.

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

## Checks
- AST parse check passed for changed Python files.
- `git diff --check` passed.
- `python manage.py check` failed before loading the project: `ModuleNotFoundError: No module named 'django'`.
- `python manage.py test dms.test_organization_tenancy --noinput` failed for the same missing Django dependency.

## Manual check required
- Run migrations and confirm existing departments, folders, documents, and document types are attached to Default Organization.
- Login as ADMIN and confirm only departments/documents from the member organization are visible.
- Login as EMPLOYEE and confirm own department subtree still works.
- Upload a document as EMPLOYEE and confirm `Document.organization` equals the user's department organization.
- Grant DocumentAccess inside one organization and confirm it does not expose another organization's document.
- Confirm document list/search/detail/view/download still work for existing documents.
