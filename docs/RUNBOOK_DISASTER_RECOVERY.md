# Disaster Recovery Runbook

This runbook describes the foundation recovery process for the DMS PostgreSQL database, media files, Qdrant search index and processing queue.

It is not a full high-availability cluster design. It does not include real secrets, vendor-specific credentials or customer document content.

## Scope

- PostgreSQL logical backup and restore.
- Media/document file backup and restore.
- Qdrant snapshot or rebuild strategy.
- Processing job recovery for stuck jobs, retries and dead-letter jobs.
- Health checks for database, storage, Qdrant, queue and worker foundation.

## Backup Policy

### PostgreSQL

Run regular logical backups from the production database host or a trusted backup runner:

```powershell
pg_dump --format=custom --no-owner --no-acl --file backup\dms_YYYYMMDD_HHMM.dump %DATABASE_URL%
```

Keep database backups encrypted at rest. Store retention outside the application host. Test restore regularly in a non-production environment.

### Media Files

Back up `DJANGO_MEDIA_ROOT` as file objects, preserving relative paths and file metadata. Do not store media backups in Git.

Example local archive command:

```powershell
Compress-Archive -Path media\* -DestinationPath backup\media_YYYYMMDD_HHMM.zip
```

For object storage, use provider-native versioning and lifecycle retention. Verify that document files and version files are included.

### Qdrant

Preferred order:

1. Use Qdrant snapshot tooling when available in the target environment.
2. If snapshots are unavailable or stale, rebuild Qdrant from PostgreSQL and document files with `reindex_search`.

Do not mix embedding models or dimensions in one collection. If `SEARCH_EMBEDDING_MODEL`, `SEARCH_EMBEDDING_VECTOR_SIZE` or `QDRANT_COLLECTION` changes, use a separate collection and reindex.

### Environment And Secrets

Back up environment configuration through the deployment secret manager, not by committing `.env`.

Must be recoverable:

- `DJANGO_SECRET_KEY`
- PostgreSQL connection settings
- Qdrant host/port/collection
- storage/media settings
- webhook secrets and integration credentials through their secret manager records

Never place real secrets in this runbook, Git, Dockerfile, Kubernetes templates or support tickets.

## Restore Steps

1. Provision a clean app environment with the same code revision.
2. Restore environment variables from the approved secret manager.
3. Restore PostgreSQL:

```powershell
pg_restore --clean --if-exists --no-owner --no-acl --dbname %DATABASE_URL% backup\dms_YYYYMMDD_HHMM.dump
```

4. Restore media files into `DJANGO_MEDIA_ROOT`.
5. Run migrations:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

6. Verify application health:

```powershell
.\.venv\Scripts\python.exe manage.py check
Invoke-WebRequest http://localhost:8000/health/
```

7. Restore or rebuild Qdrant:

```powershell
.\.venv\Scripts\python.exe manage.py reindex_search
```

8. Recover stuck processing jobs:

```powershell
.\.venv\Scripts\python.exe manage.py recover_processing_jobs --older-than-minutes 30
```

9. Verify key business flows manually: login, upload, document detail, search, AI review, workflow, exchange and evidence export.

## Processing Job Recovery

The system has a recovery command for jobs stuck in `RUNNING`:

```powershell
.\.venv\Scripts\python.exe manage.py recover_processing_jobs --older-than-minutes 30
```

Behavior:

- Jobs with retry attempts remaining are returned to `PENDING`.
- Jobs with exhausted attempts are moved to `DEAD_LETTER`.
- Locks are cleared.
- A safe recovery note is appended to `error_message`.
- Observability metrics are recorded if the observability models are available.

Dry run:

```powershell
.\.venv\Scripts\python.exe manage.py recover_processing_jobs --older-than-minutes 30 --dry-run
```

Manual restart:

```powershell
.\.venv\Scripts\python.exe manage.py recover_processing_jobs --restart-job-id 123
```

Manual dead-letter:

```powershell
.\.venv\Scripts\python.exe manage.py recover_processing_jobs --dead-letter-job-id 123
```

Django admin also exposes actions to restart selected processing jobs or move them to dead letter.

## Qdrant Rebuild Plan

Rebuild all documents:

```powershell
.\.venv\Scripts\python.exe manage.py reindex_search
```

Rebuild one organization:

```powershell
.\.venv\Scripts\python.exe manage.py reindex_search --organization-id <organization_id>
```

Rebuild stale or missing states only:

```powershell
.\.venv\Scripts\python.exe manage.py reindex_search --only-stale
```

Rebuild one document:

```powershell
.\.venv\Scripts\python.exe manage.py reindex_search --document-id <document_id>
```

Stage 40 uses versioned indexing and stable point IDs. Normal recovery should use reindex commands, not direct manual Qdrant point edits.

## Health Checks

The `/health/` endpoint reports safe operational checks only:

- database availability;
- media storage writeability;
- processing queue queryability;
- processing worker role foundation;
- optional Qdrant availability when `HEALTH_CHECK_QDRANT=True`.

Relevant settings:

```text
HEALTH_CHECK_DATABASE=True
HEALTH_CHECK_STORAGE=True
HEALTH_CHECK_QUEUE=True
HEALTH_CHECK_PROCESSING_WORKER=True
HEALTH_CHECK_QDRANT=False
DMS_PROCESSING_STUCK_JOB_MINUTES=30
```

The health response must not include secrets, file paths, secure tokens, document content or Qdrant payloads.

## Incident Checklist

1. Confirm the affected component: database, media storage, Qdrant, queue, worker or app web process.
2. Preserve logs and timestamps without copying document content or secrets into incident notes.
3. Check `/health/`.
4. Check pending/running/failed/dead-letter processing jobs.
5. Run stuck-job dry run.
6. Restore or rebuild the failed component.
7. Re-run health checks.
8. Run a small manual user-flow verification.
9. Record the recovery actions and follow-up fixes.

## Limitations

- No multi-region failover is implemented.
- No automated backup scheduler is added by this stage.
- No real Qdrant snapshot credentials or external storage credentials are stored in the repository.
- Processing worker liveness is a foundation check based on role configuration; production deployments should add a real heartbeat or external process supervisor check.
