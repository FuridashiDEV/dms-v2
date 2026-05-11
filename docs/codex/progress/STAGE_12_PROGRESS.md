# Stage 12 - API / Webhooks / Usage Tracking

Branch: `stage-12-api-webhooks-usage`

## Status

Completed and verified locally.

## Scope

- Add usage tracking as an additive layer.
- Add webhook endpoint and delivery queue foundation.
- Do not add billing, limits, payment gateway, DRF, or a full developer portal.
- Do not break existing DMS, upload, AI, import, workflow, portal, B2B, or evidence flows.
- Do not start Stage 13.

## Implementation Plan

- Add `UsageEvent`.
- Add `WebhookEndpoint` and `WebhookDelivery`.
- Add `dms/services/usage.py`.
- Record usage events from key product flows.
- Add admin registrations and a minimal organization-scoped usage view.
- Add focused tests for usage records, webhook queue creation, organization isolation, and secret redaction.

## Checks

- `makemigrations --check --dry-run`: passed.
- `manage.py check`: passed.
- `migrate --noinput` on fresh PostgreSQL: passed.
- `migrate --check`: passed.
- Stage 12 focused tests: passed (`4 tests`).
- Full `dms` test suite: passed (`74 tests`).
- `git diff --check`: passed (CRLF warnings only).

## Changed Files

- `dms/models.py`
- `dms/admin.py`
- `dms/services/usage.py`
- `dms/services/document_creation.py`
- `dms/services/imports.py`
- `dms/services/ai_processing.py`
- `dms/services/workflow.py`
- `dms/services/counterparty.py`
- `dms/views.py`
- `dms/urls.py`
- `dms/migrations/0028_usageevent_webhookendpoint_webhookdelivery_and_more.py`
- `dms/test_api_webhooks_usage.py`
- `templates/dms/usage_dashboard.html`
- `docs/codex/progress/STAGE_12_PROGRESS.md`

## Migrations

- `dms/migrations/0028_usageevent_webhookendpoint_webhookdelivery_and_more.py`

## Manual Verification Checklist

- Upload a document and confirm a `UsageEvent` is recorded.
- Create an active `WebhookEndpoint` for that event type and confirm `WebhookDelivery` is queued.
- Open `/usage/` as an authorized user and confirm only accessible organization usage appears.
- Export Legal Evidence JSON and confirm `evidence.exported` usage is recorded.
- Confirm webhook secret values and token-like metadata are not present in delivery payloads.
- Confirm no users are blocked by usage counts or limits.
- Confirm no DRF/API endpoints were added.

## Final Notes

- No payment gateway, billing, real tariffs, or limit enforcement were added.
- No DRF dependency or API endpoints were added because no API/DRF layer exists in the project.
- Webhook delivery is queue-only foundation; no outbound HTTP sender was added in this stage.
- Stage 13 was not started.

## Notes

- `docs/codex/12_API_WEBHOOKS_USAGE.md` is not present in the repository; the stage file was read from `C:\Users\Smart Product\Desktop\dmsv2\правила\12_API_WEBHOOKS_USAGE.md`.
- DRF/API endpoints are not added because DRF/API is not present in the project and the stage rules forbid installing DRF without explicit confirmation.
