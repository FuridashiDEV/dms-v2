# User Guide

## Access

Status: implemented

Users sign in at `/login/` and sign out at `/logout/`. Internal access is role and organization aware. Employees see documents allowed by their department tree, ownership, or explicit document access. Admin users can manage broader organization data according to the existing role rules.

## Dashboard

Status: implemented

The dashboard at `/` is the internal starting point. It links to documents, folders, upload/import flows, exchanges, and other product areas available to the signed-in user.

## Documents

Status: implemented

- Open the document list at `/documents/`.
- Open a document detail page at `/documents/<id>/`.
- View a protected file at `/documents/<id>/view/`.
- Download a protected file at `/documents/<id>/download/`.
- View or download a version through `/documents/<id>/versions/<version_id>/view/` and `/documents/<id>/versions/<version_id>/download/`.
- Edit document metadata at `/documents/<id>/edit/` when permissions allow.

Users should not share raw media paths. File access must go through protected document routes.

## Upload

Status: implemented

Use `/documents/upload/` to upload a single document. The current upload flow preserves `Document.file`, creates a first `DocumentVersion`, records document activity/audit/usage where available, and keeps existing organization and department access behavior.

Upload validation rejects unsafe filenames, blocked executable/script extensions, dangerous double extensions, empty files, and oversized files.

## Search

Status: partially implemented

Use `/search/` for semantic search. Search quality depends on extracted text, embeddings, and Qdrant availability/configuration. Production ranking quality must be validated manually with representative documents.

## AI Review

Status: partially implemented

AI suggestions are reviewed at `/documents/<id>/ai-review/`. Suggestions can be edited, confirmed, or rejected. Confirmed suggestions are applied only to allowed document fields. Rejected suggestions are not applied.

AI output should be treated as assistance, not final authoritative metadata, until a user confirms it.

## Workflow

Status: partially implemented

Workflow can be started from `/documents/<id>/workflow/start/`. Assigned approvers can approve, reject, request changes, or comment through `/documents/<id>/workflow/<instance_id>/<action>/`.

Workflow is an MVP approval flow. It is not a full BPMN/no-code engine.

## Exchanges

Status: partially implemented

Internal users can send a document to a counterparty from `/documents/<id>/exchanges/send/`. Exchange list and filters are available at `/exchanges/`. Incoming exchange creation is available at `/exchanges/incoming/`.

Messages for an exchange are posted through `/exchanges/<exchange_id>/messages/`.

## Evidence Export

Status: partially implemented

Authorized users can export a JSON evidence package from `/documents/<id>/evidence/export/`. The export is read-only and redacts secret/token-like data. PDF evidence export and e-signature evidence are not implemented.
