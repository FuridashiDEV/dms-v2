# Testing Guide

The project uses Django's built-in test runner and `django.test.TestCase`. No separate test framework is required.

## Run Tests

Run the full DMS suite:

```powershell
.\\.venv\\Scripts\\python.exe manage.py test dms --verbosity 1
```

Run targeted suites:

```powershell
.\\.venv\\Scripts\\python.exe manage.py test dms.test_qa_regression_strategy --verbosity 2
.\\.venv\\Scripts\\python.exe manage.py test dms.test_security_enterprise_hardening --verbosity 1
.\\.venv\\Scripts\\python.exe manage.py test dms.test_product_analytics_dashboard --verbosity 1
```

Run checks before commit:

```powershell
.\\.venv\\Scripts\\python.exe manage.py check
.\\.venv\\Scripts\\python.exe manage.py makemigrations --check --dry-run
docker compose --env-file .env.example config --quiet
```

## Test Structure

- `dms/tests.py` contains older shared tests for forms, access utilities, document detail, and validation.
- `dms/test_*` files cover stage-specific features.
- `dms/test_factories.py` contains lightweight helpers for new regression tests.
- `dms/test_qa_regression_strategy.py` contains cross-feature smoke and permission regression tests.

## Current Coverage Map

- Organization isolation: `test_organization_tenancy.py`, `test_qa_regression_strategy.py`
- Document core/versioning: `test_document_core_versioning.py`
- Audit events: `test_audit_events.py`
- AI processing: `test_ai_processing_pipeline.py`, `test_ai_parser_titles.py`
- Import: `test_import_migration_layer.py`
- Workflow: `test_workflow_engine_mvp.py`
- Counterparty portal/B2B: `test_counterparty_portal_mvp.py`, `test_b2b_document_exchange.py`, `test_b2b_communication_layer.py`
- Evidence export: `test_legal_evidence_package.py`
- Usage/webhooks: `test_api_webhooks_usage.py`
- Security: `test_security_enterprise_hardening.py`, `test_security_flows.py`
- Integration layer: `test_integration_layer.py`
- Billing: `test_billing_plans_quotas.py`
- Analytics: `test_product_analytics_dashboard.py`
- DevOps health: `test_devops_foundation.py`

## Writing New Tests

- Prefer `TestCase` and local helper functions over new dependencies.
- Keep tests organization-aware: create at least two organizations when testing permissions.
- Do not change business logic just to make a test easier.
- Use `override_settings(MEDIA_ROOT=...)` for file tests and clean temporary media in `tearDownClass`.
- Mock external or heavy services such as AI parsing, indexing, and Qdrant.
- Assert negative paths for cross-organization access and unauthenticated access.
- Avoid asserting exact translated UI copy unless the copy is the behavior under test.

## Known Manual QA Areas

- Real OCR and LLM output quality.
- Semantic search ranking quality.
- Visual responsive layout.
- Production backup/restore and TLS/reverse-proxy behavior.
