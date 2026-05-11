# Deployment Runbook

This runbook describes a production-like baseline for the DMS app. It does not add a payment gateway, S3 storage, Kubernetes, Terraform, Helm, or paid monitoring.

## Components

- Django web app served by Gunicorn.
- PostgreSQL for primary data.
- Qdrant for semantic search vectors.
- Redis reserved for future async/Celery work and lightweight infrastructure parity.
- Local Docker volumes for media, static files, logs, PostgreSQL, Redis, and Qdrant.

Celery is not started in this stage because the project does not yet define a Celery app or worker tasks. MinIO/S3 is not enabled because switching document storage away from local media requires an explicit storage decision.

## Environment

1. Copy `.env.example` to `.env`.
2. Set a strong `DJANGO_SECRET_KEY`.
3. Set `DJANGO_DEBUG=False` for production-like runs.
4. Set `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` for the real hostnames.
5. Set a strong `POSTGRES_PASSWORD`.
6. Keep `.env` out of git.

Important variables:

- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`
- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`
- `DJANGO_SESSION_COOKIE_SECURE`, `DJANGO_CSRF_COOKIE_SECURE`, `DJANGO_SECURE_SSL_REDIRECT`
- `DJANGO_STATIC_ROOT`, `DJANGO_MEDIA_ROOT`, `DJANGO_LOG_DIR`
- `QDRANT_HOST`, `QDRANT_PORT`, `QDRANT_COLLECTION`
- `HEALTH_CHECK_DATABASE`, `HEALTH_CHECK_QDRANT`

## Docker

Start dependencies only:

```powershell
docker compose up -d db redis qdrant
```

Run the full stack:

```powershell
docker compose up --build
```

The web service runs:

```text
collectstatic -> migrate -> gunicorn
```

Uploaded files are stored in the `media_data` volume and are not committed to git.

## Local Checks

```powershell
.\\.venv\\Scripts\\python.exe manage.py check
.\\.venv\\Scripts\\python.exe manage.py makemigrations --check --dry-run
.\\.venv\\Scripts\\python.exe manage.py test dms --verbosity 1
```

Health endpoint:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health/
```

By default health checks the database. Qdrant health can be enabled with `HEALTH_CHECK_QDRANT=True`, but it should only be enabled where Qdrant is expected to be reachable.

## Backup

PostgreSQL backup:

```powershell
docker compose exec db pg_dump -U $env:POSTGRES_USER -d $env:POSTGRES_DB -Fc -f /tmp/dms.backup
docker compose cp db:/tmp/dms.backup .\\backups\\dms.backup
```

Media backup:

```powershell
docker run --rm -v dms-v2_media_data:/media -v ${PWD}\\backups:/backup alpine tar czf /backup/media.tgz -C /media .
```

Qdrant backup:

```powershell
docker run --rm -v dms-v2_qdrant_data:/qdrant -v ${PWD}\\backups:/backup alpine tar czf /backup/qdrant.tgz -C /qdrant .
```

Keep database and media backups from the same maintenance window so document records and uploaded files stay consistent.

## Restore

1. Stop writes to the application.
2. Restore PostgreSQL:

```powershell
docker compose cp .\\backups\\dms.backup db:/tmp/dms.backup
docker compose exec db pg_restore -U $env:POSTGRES_USER -d $env:POSTGRES_DB --clean --if-exists /tmp/dms.backup
```

3. Restore media:

```powershell
docker run --rm -v dms-v2_media_data:/media -v ${PWD}\\backups:/backup alpine sh -c "rm -rf /media/* && tar xzf /backup/media.tgz -C /media"
```

4. Restore Qdrant only if vector data is not going to be regenerated:

```powershell
docker run --rm -v dms-v2_qdrant_data:/qdrant -v ${PWD}\\backups:/backup alpine sh -c "rm -rf /qdrant/* && tar xzf /backup/qdrant.tgz -C /qdrant"
```

5. Run:

```powershell
docker compose up -d
docker compose exec web python manage.py check
```

## Operational Notes

- Do not commit `.env` or real secrets.
- Do not put payment credentials, webhook secrets, OAuth tokens, or database passwords in Dockerfile or `docker-compose.yml`.
- Keep `DJANGO_DEBUG=False` outside local development.
- Terminate TLS at a reverse proxy and set secure cookie flags for production-like deployments.
- Keep local media storage until an explicit S3/MinIO decision is made.
