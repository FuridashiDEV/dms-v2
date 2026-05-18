# UI Unification Progress

## Scope

Unified the user-facing and operational UI added across Stage 26-48 so the new modules follow the existing DMS layout, spacing, button, card, table, badge and language patterns.

This was a UI-only stabilization pass. It did not change search core behavior, Qdrant indexing, AI processing, billing rules, quota enforcement, processing queues, audit/security behavior, migrations or permissions.

## Templates checked

- `templates/base.html`
- `templates/dms/dashboard.html`
- `templates/dms/document_list.html`
- `templates/dms/document_detail.html`
- `templates/dms/analytics_dashboard.html`
- `templates/dms/billing_dashboard.html`
- `templates/dms/billing_usage_limits.html`
- `templates/dms/cost_optimization_dashboard.html`
- `templates/dms/security_dashboard.html`
- `templates/dms/usage_dashboard.html`
- `templates/dms/evidence_report.html`
- `templates/dms/exchange_list.html`
- `templates/dms/exchange_detail.html`
- `templates/dms/incoming_exchange_form.html`
- `templates/dms/counterparty_portal.html`
- `templates/dms/notification_list.html`

## UI problems found

- Operational pages used separate visual systems (`analytics-*`, `billing-*`, `security-*`, `cost-*`, `usage-*`) instead of shared DMS page/card/table patterns.
- Top navigation exposed multiple admin/ops links as separate buttons and made the header crowded.
- Stage 48 search UX mixed English labels with the Russian UI (`Search suggestions`, `confidence`, `Basic search`, `Semantic ready`).
- Document detail mixed English labels in evidence, workflow, relation graph, retention, counterparty portal and exchange sections.
- Billing usage statuses were rendered as raw English status text instead of consistent badges.
- Some templates had mojibake separators and mixed technical copy in user-facing labels.
- Evidence report headings were English while the rest of the product UI is Russian.

## Templates changed

- `templates/base.html`
- `templates/dms/analytics_dashboard.html`
- `templates/dms/billing_dashboard.html`
- `templates/dms/billing_usage_limits.html`
- `templates/dms/cost_optimization_dashboard.html`
- `templates/dms/counterparty_portal.html`
- `templates/dms/document_detail.html`
- `templates/dms/document_list.html`
- `templates/dms/evidence_report.html`
- `templates/dms/exchange_detail.html`
- `templates/dms/exchange_list.html`
- `templates/dms/incoming_exchange_form.html`
- `templates/dms/notification_list.html`
- `templates/dms/security_dashboard.html`
- `templates/dms/usage_dashboard.html`

## Shared partials/classes added

No new partial templates were added. Minimal shared helper classes were added centrally in `templates/base.html`:

- `page-top`, `page-title`, `page-sub`, `top-actions`
- `section-title`, `section-sub`
- `ops-grid`, `ops-card`, `ops-label`, `ops-value`, `ops-note`, `ops-section`
- `data-row`, `data-main`, `data-meta`
- `badge`, `badge-success`, `badge-warning`, `badge-danger`, `badge-info`, `badge-muted`
- `empty-panel`
- `nav-group`, `nav-menu`

## Elements unified

- Page headers and top actions on new operational pages.
- Admin/ops navigation under one admin-only menu.
- Operational dashboard cards and metric blocks.
- Table/list rows and empty states.
- Billing usage status badges.
- Search mode labels, readiness labels, confidence labels and suggestions.
- Search filter labels and empty state copy.
- Document detail relation graph, evidence, workflow, retention and portal blocks.
- Evidence report headings and limitation notice.
- Counterparty exchange and notification labels.

## Intentionally not changed

- Search ranking, entity extraction, aliases, embeddings, Qdrant collections and indexing logic.
- AI processing and validation behavior.
- Billing, quota and cost calculation behavior.
- Webhook, audit, security and governance behavior.
- Permissions, organization isolation and object-level access checks.
- Routes, view function contracts and migrations.
- Raw Qdrant payload, tokens, secrets, API keys and full document contents remain hidden from UI surfaces.

## Checks

- `.\.venv\Scripts\python.exe manage.py check` - passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` - passed, no changes detected.
- `.\.venv\Scripts\python.exe manage.py migrate --check` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms --verbosity 1` - passed, 247 tests OK.
- `git diff --check` - passed.
- `git status` - reviewed.

Expected test-suite warnings were observed for intentionally tested 403/404 paths, Qdrant-unavailable fallback behavior and the health endpoint unavailable scenario.

## Manual verification needed

- Open document list and test hybrid/exact/semantic search modes with filters.
- Open a document detail page with relations, workflow, evidence, exchange messages and AI readiness data.
- Open evidence report and JSON export links from document detail.
- Open admin-only analytics, billing, billing usage, cost, security and usage dashboards.
- Verify employee users do not see admin/ops navigation and cannot open admin-only pages.
- Verify counterparty portal pages do not expose secure tokens or secrets.
- Verify search results do not reveal inaccessible documents or related documents.
