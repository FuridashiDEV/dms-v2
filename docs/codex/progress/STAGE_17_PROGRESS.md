# Stage 17 - Production Deployment / DevOps Foundation

Branch: `stage-17-production-devops-foundation`

## Status

Completed.

## Scope

- Improve production-like deployment foundation without changing product flows.
- Keep local development working.
- Keep secrets out of committed files.
- Add env documentation, health endpoint, Docker baseline, logging baseline, and deployment runbook.
- Do not add Kubernetes, Terraform, Helm, paid monitoring, S3 switch, or Stage 18 work.

## Checks

- `.\\.venv\\Scripts\\python.exe manage.py check` - passed.
- `.\\.venv\\Scripts\\python.exe manage.py makemigrations --check --dry-run` - passed, no changes detected.
- `.\\.venv\\Scripts\\python.exe manage.py test dms.test_devops_foundation --verbosity 2` - passed, 3 tests.
- `docker compose --env-file .env.example config --quiet` - passed.
- `.\\.venv\\Scripts\\python.exe manage.py test dms.test_devops_foundation dms.test_security_enterprise_hardening dms.test_product_analytics_dashboard --verbosity 1` - passed, 13 tests.
- `.\\.venv\\Scripts\\python.exe manage.py test dms --verbosity 1` - passed, 97 tests.

## Implemented

- Extended `.env.example` with production-like settings, health flags, logging paths, Redis/Celery placeholders, static/media roots, and Gunicorn options.
- Improved env-based settings parsing for integers, security flags, static/media/log paths, DB connection health checks, Redis/Celery placeholders, and health checks.
- Added `/health/` endpoint with database check and optional Qdrant check.
- Updated Dockerfile to Python 3.13, non-root runtime user, static/media/log directories, and container healthcheck.
- Updated `docker-compose.yml` with web, PostgreSQL, Redis, Qdrant, volumes, healthchecks, and no committed secrets.
- Added `.dockerignore`.
- Added `docs/DEPLOYMENT.md` with env, Docker, health, backup, restore, and operational notes.
- Added tests for health endpoint behavior and secret non-disclosure.

## Notes

- `docs/codex/17_PRODUCTION_DEVOPS_FOUNDATION.md` is not present in the repository; the stage file was read from `C:\Users\Smart Product\Desktop\dmsv2\правила\17_PRODUCTION_DEVOPS_FOUNDATION.md`.
- No S3/MinIO switch, Kubernetes, Terraform, Helm, paid monitoring, mandatory Celery worker, or Stage 18 work was added.
