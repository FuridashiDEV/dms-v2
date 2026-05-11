# Stage 14 - Integration Layer

Branch: `stage-14-integration-layer`

## Status

Completed.

## Scope

- Add integration foundation models.
- Seed standard providers safely.
- Link external references to existing `Document`.
- Keep credentials out of plaintext JSON.
- Do not add real OAuth, real Google/OneDrive/SharePoint/1C integration, e-signature, Peppol/EDI, heavy SDKs, or Stage 15 work.

## Implemented

- Added integration foundation models: `IntegrationProvider`, `IntegrationConnection`, `IntegrationSyncJob`, `ExternalReference`.
- Added safe metadata validation to block plaintext credential keys in integration JSON fields.
- Added idempotent seed migration for standard provider records.
- Added integration service helpers for provider seeding, connection creation, sync job creation, and external reference linking.
- Added admin access for integration records.
- Added AuditEvent and UsageEvent event types for integration connection/job/reference events.
- Added tests for seeded providers, plaintext secret rejection, organization isolation, external reference linking, and usage/audit recording.

## Checks

- `.\\.venv\\Scripts\\python.exe manage.py check` - passed.
- `.\\.venv\\Scripts\\python.exe manage.py makemigrations --check --dry-run` - passed, no changes detected.
- `.\\.venv\\Scripts\\python.exe manage.py test dms.test_integration_layer --verbosity 2` - passed, 5 tests.
- `.\\.venv\\Scripts\\python.exe manage.py test dms.test_integration_layer dms.test_api_webhooks_usage dms.test_security_enterprise_hardening --verbosity 1` - passed, 14 tests.
- `.\\.venv\\Scripts\\python.exe manage.py test dms --verbosity 1` - passed, 84 tests.

## Notes

- `docs/codex/14_INTEGRATION_LAYER.md` is not present in the repository; the stage file was read from `C:\Users\Smart Product\Desktop\dmsv2\правила\14_INTEGRATION_LAYER.md`.
- No real OAuth flow, external SDK, e-signature, Peppol/EDI, or Stage 15 work was added.
