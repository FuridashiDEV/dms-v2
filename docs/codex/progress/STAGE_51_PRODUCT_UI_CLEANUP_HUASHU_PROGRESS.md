# Stage 51 — Product UI Cleanup with Huashu Design

## Status

Completed.

## Stage file read

- `docs/codex/51_PRODUCT_UI_CLEANUP_HUASHU_DESIGN.md`

## Templates checked

- `templates/base.html`
- `templates/dms/document_list.html`
- `templates/dms/document_detail.html`
- `templates/dms/document_ai_review.html`
- `templates/dms/evidence_report.html`
- `templates/dms/analytics_dashboard.html`
- `templates/dms/cost_optimization_dashboard.html`
- `templates/dms/security_dashboard.html`
- `templates/dms/dashboard.html`
- `templates/dms/folder_list.html`
- `templates/dms/notification_list.html`
- `templates/dms/document_form.html`
- `templates/dms/includes/*`

## UI problems found

- Search UI mixed user-facing labels with technical terms such as Qdrant fallback, aliases, semantic layer, and English search modes.
- Document detail exposed technical JSON links, file technical parameters, SHA values, relation confidence/source, and processing/model wording too prominently.
- Evidence report displayed raw audit metadata in the human-readable UI.
- Security dashboard displayed user-agent and raw metadata without progressive disclosure.
- Operational dashboards mixed Russian labels with AI/OCR/embeddings wording and raw technical concepts.
- Search explanations and matched entities were too verbose for regular users.
- New pages did not share enough common card, badge, empty-state, explanation, and technical-details primitives.

## Templates changed

- `templates/base.html`
- `templates/dms/document_list.html`
- `templates/dms/document_detail.html`
- `templates/dms/document_ai_review.html`
- `templates/dms/evidence_report.html`
- `templates/dms/analytics_dashboard.html`
- `templates/dms/cost_optimization_dashboard.html`
- `templates/dms/dashboard.html`
- `templates/dms/document_form.html`
- `templates/dms/folder_list.html`
- `templates/dms/notification_list.html`
- `templates/dms/security_dashboard.html`

## Shared partials/classes added

- `templates/dms/includes/empty_state.html`
- `templates/dms/includes/status_badge.html`
- `templates/dms/includes/technical_details.html`
- Centralized UI helper classes in `templates/base.html`:
  - `ui-page`
  - `ui-section`
  - `ui-card`
  - `ui-card-header`
  - `ui-card-title`
  - `ui-card-meta`
  - `ui-card-body`
  - `ui-card-actions`
  - `ui-badge`
  - `ui-empty-state`
  - `ui-explanation`
  - `ui-technical-details`
  - `ui-snippet`
  - `ui-related-list`
  - `ui-related-item`

## Elements unified

- Search modes are now user-facing Russian labels:
  - `hybrid` -> `Умный поиск`
  - `exact` -> `Точный поиск`
  - `semantic` -> `Смысловой поиск`
- Search result cards now show shorter explanations, limited matched entities, contained snippets, and safer degraded-search copy.
- Technical query parsing details are visible only to staff/superusers.
- Document detail hides JSON links, MIME/SHA/source, version hash, relation confidence/source, and similar low-level details from regular users.
- AI-facing copy was softened to user-facing terms such as `предложенные поля`, `обработка`, `умный поиск`, and `краткая сводка`.
- Evidence report hides audit metadata from regular users and keeps staff-only export access.
- Security dashboard hides user-agent/raw metadata from regular users.
- Analytics and cost dashboards now use calmer operational labels instead of model/debug wording.

## Hidden from regular users

- Qdrant/model/fallback-style technical details.
- Technical query parsing details.
- Technical JSON export links.
- File MIME type, SHA/source technical details, and version checksums.
- Raw audit/security metadata and user-agent values.
- Raw search/debug payload details.

## Intentionally not changed

- Search core and ranking logic.
- Qdrant indexing and vector collections.
- Embedding/reranking/model stack.
- `SearchIndexVersion`.
- `DocumentSearchIndexState`.
- `ProcessingJob` behavior.
- Upload/import/workflow/exchange/evidence business flows.
- Billing and quota behavior.
- Permissions and organization isolation logic.
- Database models and migrations.

## Tests and checks

- `.\.venv\Scripts\python.exe manage.py check` — passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` — passed, no changes detected.
- `.\.venv\Scripts\python.exe manage.py migrate --check` — passed.
- `.\.venv\Scripts\python.exe manage.py test dms --verbosity 1` — passed, 258 tests.
- Focused UI/security regressions passed:
  - `dms.test_advanced_document_relation_graph_stage45`
  - `dms.test_enterprise_observability_stage41`
  - `dms.test_legal_evidence_package`
  - `dms.test_ai_search_ux_stage48`
  - `dms.test_product_analytics_dashboard`
  - `dms.test_cost_optimization_stage47`

Expected warnings during tests:

- Intentional 403/404 access-control checks.
- Intentional `/health/` service-unavailable test.
- Mocked Qdrant-unavailable warning.
- Hugging Face unauthenticated-request warning from model-stack tests.

## Manual verification performed

- Checked `/documents/?q=договор` as admin/staff.
- Checked `/documents/?q=договор` as regular employee.
- Checked document detail as admin/staff.
- Confirmed regular employee search page does not expose Qdrant/model/raw payload terms.
- Confirmed staff-only technical details remain available for operational users.

## Manual verification still recommended

- Review main document list/detail/search pages on a real browser viewport at desktop and mobile widths.
- Review evidence report as staff and non-staff users.
- Review analytics/security/cost dashboards with production-like data.
- Verify Russian copy with a business user before pilot/demo.
