# QA Checklist

Use this checklist before merging stage branches or preparing a pilot demo.

## Core Smoke

- Login succeeds for admin and employee users.
- Dashboard loads for authenticated users.
- Document list is organization-scoped.
- Document upload creates a document, `DocumentVersion #1`, `DocumentActivity`, `AuditEvent`, and `UsageEvent`.
- Document detail, view, download, and version download work for authorized users.
- Cross-organization users cannot open document detail, file, evidence export, AI review, workflow, or exchange routes.

## Organization And Permissions

- Admin sees only organizations they are allowed to access unless they are a superuser.
- Employee sees own department tree and explicitly shared documents only.
- Department-based access does not bypass organization isolation.
- Counterparty secure portal does not expose internal routes or token hashes.
- Analytics dashboard shows platform metrics only to superusers.

## AI Processing

- Upload can create AI processing jobs when AI is enabled.
- AI extracted fields remain suggestions until manually reviewed.
- Confirmed fields can be applied to allowed `Document` fields only.
- Rejected fields are not applied.
- AI parser failures do not break document upload.

## Workflow

- Workflow can be started for an accessible document.
- Assigned approver can approve, reject, request changes, or comment.
- Unassigned or cross-organization user cannot act.
- Document status changes match workflow outcome.
- Workflow actions create `AuditEvent`.

## Import / Exchange / Evidence

- Multi-file import creates ordinary `Document` records and versions.
- Duplicate detection by SHA-256 is reported.
- Outgoing exchange creates secure external link without storing raw token.
- Incoming exchange creates ordinary `Document` records.
- External comments are saved as messages/events.
- Evidence export includes document, versions, AI, workflow, exchanges, and audit data without secret tokens.

## Billing / Analytics / DevOps

- Usage events are recorded for key product flows.
- Billing usage-vs-limit report is read-only and does not block users.
- Analytics date filters work.
- `/health/` returns JSON without secrets.
- Docker compose config validates with `.env.example`.

## Manual-Only Checks

- OCR quality on real PDFs/scans.
- LLM output quality and latency.
- Qdrant semantic ranking quality.
- Browser layout on representative desktop/mobile widths.
- Backup/restore on real Docker volumes.
- Reverse proxy TLS, secure cookies, and domain settings in staging.
