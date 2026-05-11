# Stage 16 - Product Analytics / Admin Dashboard

Branch: `stage-16-product-analytics-dashboard`

## Status

Completed.

## Scope

- Add internal analytics service and dashboard.
- Use existing product data and `UsageEvent`; do not send data to third-party analytics.
- Provide platform metrics only to superusers.
- Provide organization-scoped metrics to organization users.
- Preserve organization isolation and existing product flows.
- Do not add external analytics SDK, BI/data warehouse, or Stage 17 work.

## Checks

- `.\\.venv\\Scripts\\python.exe manage.py check` - passed.
- `.\\.venv\\Scripts\\python.exe manage.py makemigrations --check --dry-run` - passed, no changes detected.
- `.\\.venv\\Scripts\\python.exe manage.py test dms.test_product_analytics_dashboard --verbosity 2` - passed, 5 tests.
- `.\\.venv\\Scripts\\python.exe manage.py test dms.test_product_analytics_dashboard dms.test_api_webhooks_usage dms.test_billing_plans_quotas --verbosity 1` - passed, 14 tests.
- `.\\.venv\\Scripts\\python.exe manage.py test dms --verbosity 1` - passed, 94 tests.

## Implemented

- Added `dms.services.analytics` for read-only product metrics.
- Added date range parsing with default last-30-days window.
- Added platform-level metrics for superusers only.
- Added organization-scoped metrics for organization users.
- Added `/analytics/` route and dashboard template.
- Added navigation entry for authenticated users.
- Added tests for superuser platform metrics, organization isolation, cross-organization denial, date filtering, and service aggregation.

## Notes

- `docs/codex/16_PRODUCT_ANALYTICS_DASHBOARD.md` is not present in the repository; the stage file was read from `C:\Users\Smart Product\Desktop\dmsv2\правила\16_PRODUCT_ANALYTICS_DASHBOARD.md`.
- No external analytics SDK, third-party data export, BI/data warehouse, or Stage 17 work was added.
