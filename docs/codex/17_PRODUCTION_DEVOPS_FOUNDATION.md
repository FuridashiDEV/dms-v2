# 17_PRODUCTION_DEVOPS_FOUNDATION.md

# ПУНКТ 17 — PRODUCTION DEPLOYMENT / DEVOPS FOUNDATION

## Цель

Цель этого пункта — подготовить проект к стабильному production-like запуску для B2B-пилотов.

После предыдущих пунктов система уже имеет продуктовую логику:

- organizations;
- documents;
- document versions;
- AI processing;
- import;
- workflow;
- counterparty portal;
- B2B exchange;
- evidence export;
- usage;
- billing foundation;
- analytics;
- security baseline.

Теперь нужно подготовить инфраструктурную основу.

Важно:

На этом пункте нельзя переписывать приложение.

Нужно подготовить окружение так, чтобы проект можно было запускать предсказуемо:

```text
Django app
PostgreSQL
Redis
Celery worker
Celery beat, if needed
Qdrant, if used
MinIO / S3-compatible storage
Nginx, if safe
.env config
health checks
backup notes