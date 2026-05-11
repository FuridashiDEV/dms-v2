# Product Overview

## Scope

This project is a Django/PostgreSQL DMS with organization-aware document storage, protected file access, document versions, audit and usage records, AI-assisted metadata review, imports, workflow MVP, counterparty exchange, evidence export, integration foundations, billing foundations, analytics, and deployment/QA documentation.

## Core Product Areas

### Organizations, Users, Roles, Departments

Status: implemented

- `Organization` and `OrganizationMember` scope users to tenant data.
- `Department` provides department hierarchy for document access.
- The existing `ADMIN` and `EMPLOYEE` role behavior remains the main internal authorization model.
- Superusers can access platform-level admin and analytics surfaces.

### Documents And Versions

Status: implemented

- Documents are ordinary `Document` records with `Document.file` preserved for backward compatibility.
- Upload and import flows create `DocumentVersion` records.
- Protected view/download endpoints are used for document and version files.
- `DocumentActivity`, `AuditEvent`, and `UsageEvent` record relevant document flows.

### AI Processing And Review

Status: partially implemented

- Current AI parser logic is wrapped by processing services.
- AI results are stored as editable `ExtractedField` suggestions.
- Document metadata is changed only after manual review.
- Heavy asynchronous AI processing and production OCR/LLM quality guarantees are not implemented.

### Import / Migration Layer

Status: implemented

- Multiple file import creates ordinary `Document` records.
- Imported documents receive versions.
- Duplicate detection uses SHA-256 where available.
- Import does not replace the single document upload flow.

### Workflow MVP

Status: partially implemented

- Workflow templates, step templates, instances, and actions exist.
- Start, approve, reject, request changes, and comment actions are available for assigned approvers.
- Document status is updated by workflow outcomes.
- This is not a BPMN engine or no-code workflow builder.

### Counterparty Portal And B2B Exchange

Status: partially implemented

- Outgoing exchanges create secure token-based external portal links.
- External users can view a scoped exchange, download the related file, and accept/reject/comment.
- Incoming exchange flow can create ordinary internal documents.
- B2B message history exists around `DocumentExchange`, but there are no full external accounts or real-time chat.

### Legal Evidence Package

Status: partially implemented

- Evidence export returns JSON for a single authorized document.
- Export includes document data, organization context, versions, AI fields, workflow, exchanges, and audit records.
- Raw secure tokens, secrets, API keys, and server file paths are not included.
- PDF evidence packages and e-signature evidence are not implemented.

### Usage, Webhooks, API, Billing

Status: foundation only

- Usage events are recorded for key product flows.
- Webhook endpoint and delivery models exist as a queue foundation.
- Billing plans, quotas, subscriptions, and usage-vs-limit reporting exist as a read-only foundation.
- There is no full public API, no developer portal, no payment gateway, and no hard quota enforcement.

### Integrations

Status: foundation only

- Integration provider, connection, sync job, and external reference models exist.
- Standard providers can be seeded.
- External references link external records to existing documents.
- Real OAuth, token storage, and live sync with Google Drive, OneDrive, SharePoint, 1C, Peppol, EDI, or EDS are not implemented.

### Analytics

Status: partially implemented

- Platform metrics are available to superusers.
- Organization metrics are available to organization-scoped users.
- Date range filtering is available.
- This is not a data warehouse or BI product.

## Key Limitations

- No e-signature or EDS support.
- No full public API.
- No real payment flow.
- No external compliance certification claims.
- No real-time communication layer.
- No production antivirus dependency is bundled.
- Real OCR/LLM output quality, semantic ranking, and production backup/restore require manual validation.
