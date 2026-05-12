# Stage 20 - Related Documents

Branch: `stage-20-related-documents`

## Status

Completed.

## Scope

- Use the existing `DocumentRelation` model as the foundation for related documents.
- Add a manual relation form to the existing document detail page.
- Add create/delete relation flows around existing `Document`.
- Enforce organization isolation and existing object-level document permissions.
- Record `AuditEvent` and `UsageEvent` for relation create/delete.
- Include visible related documents in evidence export.
- Add focused regression tests.
- Do not create a separate contract system, do not start Stage 21, and do not add AI auto-linking.

## Implemented

- Added relation management service in `dms/services/document_relations.py`.
- Added `DocumentRelationForm`.
- Added document relation add/delete routes and views.
- Updated document detail to show a relation form, accessible direct/reverse links, and remove actions for users with relation-management rights.
- Extended `DocumentRelation.RelationType` choices for Stage 20 relation types.
- Added audit and usage event types for relation create/delete.
- Added evidence export `related_documents` section filtered by organization and user-visible documents.
- Added `dms/test_related_documents.py`.

## Checks

- `.\\.venv\\Scripts\\python.exe manage.py check` - passed.
- `.\\.venv\\Scripts\\python.exe manage.py test dms.test_related_documents --verbosity 2` - passed, 5 tests.
- `.\\.venv\\Scripts\\python.exe manage.py test dms.test_related_documents --verbosity 1` - passed, 5 tests.
- `.\\.venv\\Scripts\\python.exe manage.py makemigrations --check --dry-run` - passed, no changes detected.
- `.\\.venv\\Scripts\\python.exe manage.py migrate --check` - initially returned non-zero because local DB had unapplied migrations; after local `.\\.venv\\Scripts\\python.exe manage.py migrate`, passed.
- `.\\.venv\\Scripts\\python.exe manage.py test dms --verbosity 1` - passed, 106 tests.
- `git diff --check` - passed.

## Manual Verification

- Open a document detail page and confirm the related documents block is visible.
- Add a relation to another accessible document from the same organization.
- Confirm the direct relation appears on the source document.
- Open the related document and confirm the reverse relation appears.
- Remove the relation and confirm neither document is deleted.
- Confirm users cannot select inaccessible or cross-organization documents.
- Export evidence and confirm `related_documents` includes only accessible same-organization documents.

## Notes

- No separate contract system was added.
- No Stage 21 work was started.
- No AI auto-linking was added.
