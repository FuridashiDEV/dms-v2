# Stage 13 - Security / Enterprise Hardening

Branch: `stage-13-security-enterprise-hardening`

## Status

Completed and verified locally.

## Scope

- Harden current DMS/B2B flows without rewriting auth or business logic.
- Strengthen object-level permission coverage and organization isolation.
- Harden external portal token handling.
- Harden file upload validation and prepare antivirus hook.
- Mask sensitive data in logs/payloads.
- Add `docs/SECURITY_BASELINE.md`.
- Do not add SSO/SAML, paid security services, heavy dependencies, SOC2 automation, or Stage 14 work.

## Checks

- `makemigrations --check --dry-run`: passed.
- `manage.py check`: passed.
- `migrate --noinput` on fresh PostgreSQL: passed.
- `migrate --check`: passed.
- Stage 13 focused tests: passed (`5 tests`).
- Full `dms` test suite: passed (`79 tests`).
- `git diff --check`: passed (CRLF warnings only).

## Changed Files

- `.gitignore`
- `dms/forms.py`
- `dms/services/security.py`
- `dms/services/counterparty.py`
- `dms/views.py`
- `dms/test_security_enterprise_hardening.py`
- `templates/dms/document_detail.html`
- `docs/SECURITY_BASELINE.md`
- `docs/codex/progress/STAGE_13_PROGRESS.md`

## Migrations

- None.

## Manual Verification Checklist

- Upload allowed file types and confirm upload still works.
- Try executable/double-extension/script MIME uploads and confirm validation blocks them.
- Open/download document files and document versions as authorized user.
- Confirm file responses include no-store/nosniff/referrer-policy/frame headers.
- Confirm unauthorized department user cannot access edit/download/version download.
- Create counterparty exchange and confirm raw secure token is not stored in audit metadata or shown on document detail.
- Confirm Counterparty Portal secure token flow still opens/downloads/accepts/rejects/comments.
- Confirm evidence export still redacts token-like/secret-like metadata.
- Confirm webhook payloads do not include secrets.

## Final Notes

- No SSO/SAML, paid security service, heavy dependency, or SOC2/ISO automation was added.
- Antivirus is prepared as optional `settings.DMS_ANTIVIRUS_SCANNER`; no real scanner dependency was installed.
- Stage 14 was not started.

## Notes

- `docs/codex/13_SECURITY_ENTERPRISE_HARDENING.md` is not present in the repository; the stage file was read from `C:\Users\Smart Product\Desktop\dmsv2\правила\13_SECURITY_ENTERPRISE_HARDENING.md`.
- Existing uncommitted `.gitignore` change adds `.env`; this is security-related and will be included in this stage rather than reverted.
