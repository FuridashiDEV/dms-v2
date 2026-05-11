# DMS Documentation Index

This documentation describes the current product state after the staged DMS build-out. It is intentionally conservative: features are marked as implemented, partially implemented, foundation only, or planned where the codebase does not yet provide a complete production workflow.

## Status Labels

- `Status: implemented` means the feature has a route, model/service/admin support, or tested flow in the current project.
- `Status: partially implemented` means the MVP flow exists, but production depth, async processing, external integrations, or full UX coverage is limited.
- `Status: foundation only` means the data model/service/admin base exists, but real external connectivity, enforcement, or product UI is not complete.
- `Status: planned` means the project does not currently implement the feature.

## Product And User Docs

- [Product Overview](PRODUCT_OVERVIEW.md) - product scope, routes, feature status, and limitations.
- [User Guide](USER_GUIDE.md) - internal employee/admin document workflows.
- [Admin Guide](ADMIN_GUIDE.md) - users, organizations, admin models, and operational controls.
- [Counterparty Portal Guide](COUNTERPARTY_PORTAL_GUIDE.md) - secure external exchange page and external actions.
- [Import, AI, And Workflow Guide](IMPORT_AI_WORKFLOW_GUIDE.md) - imports, AI review, workflow MVP.
- [B2B And Evidence Guide](B2B_EVIDENCE_GUIDE.md) - exchanges, messages, incoming documents, evidence JSON export.
- [Integrations, API, Webhooks, And Billing Guide](INTEGRATIONS_API_BILLING_GUIDE.md) - foundation-level integration/API/webhook/billing capabilities.

## Operations, Security, And QA

- [Security Baseline](SECURITY_BASELINE.md) - current hardening baseline and security limitations.
- [Deployment Runbook](DEPLOYMENT.md) - environment, Docker, health check, backup, restore.
- [Testing Guide](TESTING.md) - test runner, test map, commands.
- [QA Checklist](QA_CHECKLIST.md) - manual and automated verification checklist.
- [Demo Runbook](DEMO_RUNBOOK.md) - demo-oriented workflow notes.
- [Client Demo Script](CLIENT_DEMO_SCRIPT.md) and [Client Pitch Deck](CLIENT_PITCH_DECK.md) - client-facing presentation material.

## Current Route Map

- Internal app: `/`, `/documents/`, `/documents/upload/`, `/documents/import/`, `/imports/<id>/`, `/folders/`, `/users/`, `/analytics/`, `/usage/`.
- Document actions: `/documents/<id>/`, `/documents/<id>/edit/`, `/documents/<id>/view/`, `/documents/<id>/download/`, `/documents/<id>/versions/<version_id>/view/`, `/documents/<id>/versions/<version_id>/download/`.
- AI and search: `/documents/<id>/ai-review/`, `/ai/parse/`, `/search/`.
- Workflow: `/documents/<id>/workflow/start/`, `/documents/<id>/workflow/<instance_id>/<action>/`.
- Exchange: `/exchanges/`, `/exchanges/incoming/`, `/documents/<id>/exchanges/send/`, `/exchanges/<exchange_id>/messages/`.
- External portal: `/portal/exchanges/<token>/`, `/portal/exchanges/<token>/download/`, `/portal/exchanges/<token>/<action>/`.
- Evidence: `/documents/<id>/evidence/export/`.
- Platform: `/login/`, `/logout/`, `/admin/`, `/health/`.

## Explicit Non-Claims

- No e-signature or EDS workflow is implemented.
- No full public developer API or developer portal is implemented.
- No real OAuth integration with Google Drive, OneDrive, SharePoint, or 1C is implemented.
- No payment gateway, invoicing, or hard quota enforcement is implemented.
- No SOC2, ISO, or other external certification is claimed.
- No real-time chat or WebSocket layer is implemented.
