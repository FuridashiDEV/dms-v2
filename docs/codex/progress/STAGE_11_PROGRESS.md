# Stage 11 - Legal Evidence Package

Branch: `stage-11-legal-evidence-package`

## Status

Completed and verified locally.

## Scope

- Add a read-only evidence service for existing DMS data.
- Export JSON evidence packages for accessible documents.
- Include document, organization, versions, AI fields, workflow, exchanges, messages, and audit events.
- Do not change existing document, audit, AI, workflow, portal, or B2B exchange logic.
- Do not add PDF export, e-signature, blockchain, billing, or Stage 12 work.

## Implementation Plan

- Add `dms/services/evidence.py`.
- Add export route/view guarded by existing document access checks.
- Add a document detail link for JSON export.
- Record `AuditEvent` using the closest available audit type and `evidence_exported` metadata.
- Add focused tests for permissions, organization isolation, included sections, and secret redaction.

## Checks

- `makemigrations --check --dry-run`: passed.
- `manage.py check`: passed.
- `migrate --noinput` on fresh PostgreSQL: passed.
- `migrate --check`: passed.
- Stage 11 focused tests: passed (`4 tests`).
- Full `dms` test suite: passed (`70 tests`).
- `git diff --check`: passed (CRLF warnings only).

## Changed Files

- `dms/services/evidence.py`
- `dms/views.py`
- `dms/urls.py`
- `dms/test_legal_evidence_package.py`
- `templates/dms/document_detail.html`
- `docs/codex/progress/STAGE_11_PROGRESS.md`

## Migrations

- None.

## Manual Verification Checklist

- Login as a user who can access a document.
- Open document detail.
- Click `Evidence JSON`.
- Confirm JSON downloads/opens and contains document, organization, versions, AI, workflow, exchanges, and audit sections.
- Confirm secure token values, token hashes, token hints, portal URLs, server file paths, raw file contents, and API secrets are not present.
- Confirm an inaccessible department document returns 404/forbidden behavior through existing access controls.
- Confirm an `AuditEvent` is recorded with `metadata.evidence_exported = true`.

## Final Notes

- No models were changed.
- No migration was created.
- No PDF export, e-signature, blockchain, billing, or Stage 12 work was added.

## Notes

- `docs/codex/11_LEGAL_EVIDENCE_PACKAGE.md` is not present in the repository; the stage file was read from `C:\Users\Smart Product\Desktop\dmsv2\правила\11_LEGAL_EVIDENCE_PACKAGE.md`.
