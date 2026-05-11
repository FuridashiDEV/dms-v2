# Stage 15 - Billing / Plans / Quotas Foundation

Branch: `stage-15-billing-plans-quotas`

## Status

Completed.

## Scope

- Add internal billing foundation only.
- Add plans, subscriptions, quota definitions, monthly usage aggregation, and usage-vs-limit reporting.
- Seed baseline plans safely.
- Create default subscriptions for existing organizations through migration.
- Do not add payment gateways, real invoices, money movement, hard quota enforcement, accounting, or Stage 16 work.

## Checks

- `.\\.venv\\Scripts\\python.exe manage.py check` - passed.
- `.\\.venv\\Scripts\\python.exe manage.py makemigrations --check --dry-run` - passed, no changes detected.
- `.\\.venv\\Scripts\\python.exe manage.py test dms.test_billing_plans_quotas --verbosity 2` - passed, 5 tests.
- `.\\.venv\\Scripts\\python.exe manage.py test dms.test_billing_plans_quotas dms.test_api_webhooks_usage dms.test_integration_layer --verbosity 1` - passed, 14 tests.
- `.\\.venv\\Scripts\\python.exe manage.py test dms --verbosity 1` - passed, 89 tests.

## Implemented

- Added billing foundation models: `Plan`, `PlanQuota`, `Subscription`.
- Added report-only quota definitions by `UsageEvent.event_type`.
- Added billing service for base plan seeding, default subscription creation, monthly usage aggregation, and usage-vs-limit reporting.
- Added idempotent data migration to seed base plans and create default subscriptions for existing organizations.
- Added Django admin access for plans, quotas, and subscriptions.
- Added AuditEvent type and audit logging when the service creates a default subscription.
- Added tests for seeded plans/quotas, subscription creation/reuse, monthly aggregation, limit reporting, and non-enforcement.

## Notes

- `docs/codex/15_BILLING_PLANS_QUOTAS.md` is not present in the repository; the stage file was read from `C:\Users\Smart Product\Desktop\dmsv2\правила\15_BILLING_PLANS_QUOTAS.md`.
- No payment gateway, Stripe/Kaspi/CloudPayments, real invoices, money movement, hard quota enforcement, accounting, or Stage 16 work was added.
