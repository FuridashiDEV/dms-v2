# Production Pilot Runbook

Status: pilot readiness guide

This runbook prepares a controlled pilot environment. It does not claim SOC2/ISO certification, e-signature compliance, payment readiness, or full public API readiness.

## Pilot Scope

The pilot should validate the existing DMS flows with agreed non-production or approved client data:

- organization, departments, folders, and users;
- single document upload and multi-file import;
- document list/detail/view/download/version access;
- search with exact, semantic, and hybrid modes;
- AI suggestions with manual review before applying metadata;
- workflow MVP approval routes;
- counterparty exchange and secure external portal;
- evidence JSON/human-readable report;
- notifications, audit, usage, billing foundation, analytics, security dashboard;
- backup, restore, health checks, and rollback.

## Go / No-Go Checklist

Before pilot start:

- `DJANGO_DEBUG=False`.
- `DJANGO_SECRET_KEY` is strong and unique for the pilot environment.
- `POSTGRES_PASSWORD` is strong and not a placeholder.
- `DJANGO_ALLOWED_HOSTS` contains the real pilot host.
- `DJANGO_CSRF_TRUSTED_ORIGINS` contains the pilot HTTPS origin.
- HTTPS is terminated by a reverse proxy.
- `DJANGO_SESSION_COOKIE_SECURE=True`.
- `DJANGO_CSRF_COOKIE_SECURE=True`.
- `DJANGO_SECURE_SSL_REDIRECT=True` if TLS termination supports it.
- `DJANGO_SECURE_HSTS_SECONDS` is set for the environment policy.
- `.env` is not committed and secrets are not stored in Dockerfiles or docs.
- `/health/` returns `status=ok`.
- `validate_production_security` has no errors.
- `check_pilot_readiness` has no errors; warnings are reviewed and accepted.
- PostgreSQL backup is tested.
- Media backup is tested.
- Restore has been tested on a non-production target.
- Admin and user onboarding accounts are prepared.
- Pilot limitations are communicated to the customer.

## Environment Setup

Use [Deployment Runbook](DEPLOYMENT.md) as the base. Minimum pilot variables:

```env
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<strong unique value>
DJANGO_ALLOWED_HOSTS=pilot.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://pilot.example.com
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SECURE_HSTS_SECONDS=31536000
POSTGRES_PASSWORD=<strong unique value>
HEALTH_CHECK_DATABASE=True
HEALTH_CHECK_QDRANT=False
```

Set `HEALTH_CHECK_QDRANT=True` only if Qdrant is required and reachable in the pilot environment.

Optional security controls:

```env
DMS_ORGANIZATION_IP_ALLOWLISTS={"demo-university":["203.0.113.0/24"]}
DMS_ANTIVIRUS_SCANNER=
DMS_ANTIVIRUS_FAIL_CLOSED=False
```

Enable `DMS_ANTIVIRUS_FAIL_CLOSED=True` only after the scanner hook has been tested.

## Pilot Data

For internal demos or dry runs, use:

```powershell
.\.venv\Scripts\python.exe manage.py prepare_demo_data
```

For a real customer pilot:

- use only data approved by the customer;
- avoid personal data unless the pilot agreement permits it;
- avoid production legal documents unless backup/retention expectations are agreed;
- record what data was loaded and who approved it;
- delete or archive pilot data according to the pilot exit plan.

## Preflight Commands

Run before handoff:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py validate_production_security
.\.venv\Scripts\python.exe manage.py check_pilot_readiness
docker compose --env-file .env.example config --quiet
```

Run the full suite before pilot release:

```powershell
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
```

## Health Checks

Basic endpoint:

```powershell
Invoke-WebRequest https://pilot.example.com/health/
```

Expected response:

```json
{"status":"ok","checks":{"database":"ok"}}
```

The health endpoint must not expose secrets, database URLs, tokens, or filesystem paths.

## Backup Checklist

Before pilot start and before each risky maintenance window:

1. Create PostgreSQL backup.
2. Create media backup.
3. Create Qdrant backup or confirm vectors can be regenerated.
4. Store backups outside the application container.
5. Record backup timestamp, operator, environment, and storage location.
6. Verify backup file sizes are non-zero.
7. Keep database and media backups from the same maintenance window.

Reference commands are in [Deployment Runbook](DEPLOYMENT.md).

## Restore Checklist

Test restore before customer pilot:

1. Restore PostgreSQL into a non-production database.
2. Restore media into a non-production media volume.
3. Restore Qdrant or run search reindex.
4. Run migrations/checks.
5. Open `/health/`.
6. Login as admin.
7. Open representative documents and verify files download.
8. Verify search returns expected documents.
9. Verify audit/security dashboard loads.

## Admin Onboarding

Pilot admin should know how to:

- login/logout;
- create departments, folders, and users;
- assign roles and departments;
- upload/import documents;
- grant/revoke document access;
- review audit/security dashboard;
- export audit CSV;
- monitor usage/billing foundation screens;
- use backup/restore runbook;
- report bugs without sharing secure portal tokens or secrets.

## User Onboarding

Pilot users should know how to:

- login/logout;
- navigate dashboard, folders, and document list;
- upload a document;
- search and filter documents;
- open document detail, versions, and related documents;
- review AI suggestions before applying them;
- participate in workflow actions assigned to them;
- use counterparty exchange only for approved pilot scenarios.

## Pilot QA Scenario

Run this with a prepared organization:

1. Admin logs in and verifies dashboard.
2. Admin creates/checks department/folder structure.
3. Employee uploads a document.
4. Document detail shows version, checksum, audit/activity, and protected file actions.
5. Search finds the document by title, metadata, and representative business query.
6. AI processing creates suggestions; user confirms/rejects manually.
7. Workflow is started and approver completes approve/reject/request changes.
8. Counterparty exchange link is created and opened externally.
9. External comment/accept/reject is recorded.
10. Evidence report/export is generated by an authorized user.
11. Notifications, audit events, usage, analytics, billing, and security dashboard are reviewed.
12. Backup is created.
13. Restore is tested on a non-production target.

## Known Limitations

- No e-signature or EDS.
- No SOC2/ISO certification claim.
- No real payment gateway, invoices, or hard quota enforcement.
- No full public developer portal.
- OAuth integrations are foundation only unless separately implemented and tested.
- AI extraction quality must be validated manually on customer document samples.
- Semantic search quality depends on text extraction, embeddings, Qdrant availability, and representative indexing.
- Webhooks are queued foundation delivery; external receiver behavior must be tested per customer.
- Antivirus is a hook unless a real scanner is configured.

## Rollback Plan

If pilot deployment fails:

1. Stop user writes or put the environment behind maintenance mode at the reverse proxy.
2. Preserve logs and current database/media state for investigation.
3. Restore the latest known-good database and media backup.
4. Re-run migrations/checks for the restored version.
5. Run `/health/`.
6. Login as admin and verify representative documents.
7. Notify pilot stakeholders with the exact impact window and current status.

Do not delete pilot data until the customer and project owner approve the cleanup plan.
