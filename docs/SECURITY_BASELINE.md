# Security Baseline

Status: foundation only

This project uses incremental hardening around the existing Django DMS flows. This document records the current baseline and the boundaries intentionally left for later stages.

## Access Control

- Internal document access must go through `get_allowed_documents()` and `user_can_access_document()`.
- Organization isolation is enforced through organization-scoped querysets and department-based access.
- External counterparty access is token-based and scoped to a single `DocumentExchange`.
- Evidence export is read-only and uses the same object-level document access checks as document detail/download.

## File Access

- Files are served through protected Django views, not direct public media URLs.
- Protected file responses set:
  - `Cache-Control: private, no-store`
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: no-referrer`
  - `X-Frame-Options: SAMEORIGIN`
- Existing upload, preview, download, and version download URLs remain backward compatible.

## Upload Validation

- Uploads reject empty files, oversized files, unsafe filenames, blocked executable extensions, dangerous double extensions, and blocked executable/script MIME types.
- Current max file size is 50 MB.
- Antivirus scanning is prepared through optional `settings.DMS_ANTIVIRUS_SCANNER`.
- No antivirus dependency is bundled in this stage.

## External Portal

- Secure portal tokens must never be logged or stored in audit/usage/webhook payloads.
- Normal internal UI must not display token hints.
- Token resolution uses SHA-256 hashes and does not expose raw token values.

## Enterprise Security Controls

- Security dashboard is available to superusers and organization admins at `/security/`.
- Audit CSV export is access controlled and scoped to organizations the user may administer.
- Exported audit metadata is redacted for token, secret, password, API key, private key, authorization, cookie, and session-like keys.
- Optional organization IP allowlists can be configured through `DMS_ORGANIZATION_IP_ALLOWLISTS` as JSON keyed by organization id or slug.
- IP allowlist enforcement does not apply to normal login, logout, health, or external portal routes.
- Login success, login failure, login rate limiting, IP allowlist denial, and audit export are recorded as security audit events.
- Production settings can be checked with `python manage.py validate_production_security`.

## Audit, Usage, Evidence, Webhooks

- AuditEvent remains independent from UsageEvent.
- Evidence JSON redacts token-like and secret-like metadata keys.
- Webhook delivery payloads are queued only and sanitized before persistence.
- Webhook secrets are stored only as hashes; raw secrets must not be logged or shown in UI.

## Operational Notes

- `.env` is ignored by Git.
- Production should set secure Django settings: HTTPS, secure cookies, strict allowed hosts, CSRF trusted origins, and external media storage policy.
- `DMS_ANTIVIRUS_SCANNER` remains optional. `DMS_ANTIVIRUS_FAIL_CLOSED=True` can be used in stricter environments to reject uploads when the scanner hook is unavailable.
- Future stages may add SSO/SAML, real antivirus, SIEM forwarding, and compliance automation. They are intentionally out of scope for this baseline.
- This document is not a SOC2, ISO, or other certification claim.
