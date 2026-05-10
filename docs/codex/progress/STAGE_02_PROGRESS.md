# STAGE 02 PROGRESS

## Stage
Core DMS stabilization.

## Branch
stage-02-core-stabilization

## Current status
Completed with environment check caveat: Django is not installed in the local Python environment, so Django system checks/tests could not run here.

## Scope
- Preserve current upload flow, forms, URLs, templates, roles, department-based access, DocumentAccess, DocumentActivity, and AI extraction/metadata parsing.
- Stabilize existing core behavior without adding Organization, multi-tenancy, workflow, portal, exchange, AuditEvent, or new DocumentVersion model.

## Work log
- Created stage branch from `origin/main`.
- Started from the Stage 01 audit findings.
- Added a document indexing service to centralize embedding/Qdrant indexing and deletion.
- Made Qdrant vector-store operations return safe values instead of raising when the vector service is unavailable.
- Reused the existing document list search from the `/search/` route to avoid the missing `semantic_search.html` template path.
- Tightened document delete lookup to use the existing allowed-document queryset before delete permission checks.
- Added focused tests for delete access probing and vector-store resilience.

## Checks
- `python manage.py check` failed before loading the project: `ModuleNotFoundError: No module named 'django'`.
- `python manage.py test dms.test_vector_store_resilience dms.test_security_flows.DocumentAccessManagementTests --noinput` failed for the same missing Django dependency.
- AST parse check passed for changed Python files.
- `git diff --check` passed.

## GitHub
- Local commit created.
- Push blocked by GitHub permissions: current credentials are denied write access to `FuridashiDEV/dms-v2`.

## Manual check required
- Login as ADMIN and upload a document with file extraction enabled.
- Login as EMPLOYEE and upload into own department.
- Confirm additional `DocumentAccess` departments can see the document.
- Confirm unrelated department user cannot open/delete the document.
- Confirm document list search works through `/documents/?q=...`.
- Confirm `/search/?q=...` renders the same existing document list search flow.
- Confirm Qdrant/Ollama unavailable states do not block manual document upload.

## Notes
- `docs/codex/02_CORE_STABILIZATION.md` is not present in the repository; final reporting will follow `правила/02_CORE_STABILIZATION.md`.
