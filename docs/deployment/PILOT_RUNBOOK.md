# Pilot Runbook

## Daily checks

1. Open health endpoint.
2. Review failed ProcessingJob count.
3. Review audit/security dashboard for unusual login or access failures.
4. Confirm backup completed.
5. Check disk usage for database and media.

## Deploy

1. Pull reviewed branch/release.
2. Install dependencies.
3. Run:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
```

4. Restart web service.
5. Run smoke tests from the checklist.

## Backup

- Database: use PostgreSQL native dump.
- Media: copy persistent media directory.
- Config: record environment variable names, not secret values.
- Qdrant: treat vectors as rebuildable from documents unless pilot explicitly chooses vector backup.

## Restore

1. Stop web service.
2. Restore database.
3. Restore media.
4. Restore `.env` from secure secret storage.
5. Run migrations if needed.
6. Rebuild search index if Qdrant was not restored.
7. Run smoke tests.

## Incident response

- Access leak suspicion: disable affected user/link, preserve audit logs, export scoped evidence, review organization and document permissions.
- AI/OCR failure: keep upload flow alive, mark processing job failed, retry manually after root cause.
- Qdrant unavailable: rely on safe fallback/basic search, do not expose raw payloads.
- Webhook outage: keep business flow working; retry delivery queue later.

## Future scaling path

Kubernetes, KEDA, GPU workers and distributed AI processing are documented as foundation/future scaling path. They are not required for first controlled pilot.
