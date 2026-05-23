# Pilot Deployment Checklist

## Server

- Linux VM or Windows Server suitable for controlled pilot.
- 4 CPU / 8-16 GB RAM minimum for web + Postgres + light search.
- Additional RAM/VRAM only if heavy local embedding/OCR models are enabled.
- Time synchronization enabled.
- TLS termination through reverse proxy.

## Runtime

- Python version matching local `.venv`.
- Django dependencies installed from project requirements.
- Environment variables loaded from `.env`, never committed.
- `DEBUG=False` for pilot-like environment.
- Strong `SECRET_KEY`.
- Correct `ALLOWED_HOSTS` and CSRF trusted origins.

## Database

- PostgreSQL configured with regular backups.
- Migrations applied:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

- Smoke check:

```powershell
.\.venv\Scripts\python.exe manage.py check
```

## Storage and media

- Persistent media directory configured.
- Upload size and extension validation enabled.
- Backups include database and media files.
- Do not move to S3/MinIO without explicit pilot decision.

## Search and AI

- Qdrant optional but recommended for semantic search pilot.
- One Qdrant collection per embedding model.
- Default model: configured `SEARCH_EMBEDDING_MODEL` (`BAAI/bge-m3` in current settings).
- Heavy models are not loaded by benchmark commands unless explicitly requested.
- OCR/AI processing policy should avoid expensive processing for every upload by default.

## Users and organizations

- Create pilot organization.
- Create one organization admin.
- Create employee roles by department.
- Verify department-based access and `DocumentAccess`.
- Disable demo accounts outside demo environment.

## Backup / restore

- Daily DB backup for pilot.
- Media backup at same cadence.
- Restore drill before first customer pilot.
- Document restore target: database, media, `.env`, Qdrant rebuild procedure.

## Monitoring

- Health endpoint checked by uptime monitor.
- Django logs collected with secret redaction.
- Processing queue and failed job dashboard reviewed daily.
- Webhook failures should not block user flows.

## Security checklist

- `DEBUG=False`.
- No secrets in repository.
- Staff-only technical details verified.
- Evidence exports do not include tokens, passwords, raw payloads or server file paths.
- Search and related documents respect organization and object-level permissions.
- External portal links have expiry/revocation behavior.

## Post-deployment verification

- Login works.
- Upload works.
- Document list/detail works.
- Search works with safe fallback.
- Evidence report works for authorized user only.
- B2B exchange link works and expires/revokes.
- Backup job completes.
- Restore command/runbook reviewed.

## Rollback plan

- Keep previous release artifact/commit.
- Snapshot database and media before migration.
- Roll back application code first.
- Restore DB/media only if schema/data migration requires it.
- Do not delete Qdrant collection as a rollback shortcut.
