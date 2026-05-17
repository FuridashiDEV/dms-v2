# Kubernetes AI Orchestration Foundation

These manifests are templates for making the DMS AI processing center Kubernetes-ready. They are not required for local development and do not replace `docker-compose.yml`.

## Roles

- `web` serves Django through Gunicorn and exposes `/health/`.
- `scheduler` runs `run_processing_role --role scheduler` for fan-out/fan-in queue coordination.
- `ocr-worker` handles `OCR` and `TEXT_EXTRACTION` processing jobs.
- `entity-worker` handles `AI_PARSE` and `ENTITY_EXTRACTION` processing jobs.
- `embedding-worker` handles `CHUNKING` and `EMBEDDING` processing jobs.
- `rerank-worker` handles `RERANKING` processing jobs.
- `qdrant-index-worker` handles `REINDEX` jobs through the existing local `index_document()` service.
- `notification-worker` is a reserved healthchecked role for future async notification fan-out.

## Files

- `namespace.yaml` creates the example namespace.
- `configmap.yaml` contains non-secret settings.
- `secret.example.yaml` shows required secret keys with placeholder values only.
- `web.yaml` defines the web Deployment and Service.
- `scheduler.yaml` defines the scheduler Deployment.
- `workers.yaml` defines CPU worker Deployments.
- `gpu-worker.yaml` defines an optional GPU embedding worker template with `nvidia.com/gpu` resources.
- `keda-scaledobject.example.yaml` shows a KEDA-compatible PostgreSQL scaler for embedding queue depth.

## Local mode

Local development remains Docker Compose based:

```powershell
docker compose up --build
```

The Kubernetes manifests should not be applied blindly. Replace image names, hosts, storage, ingress and secret management for the target environment.

## KEDA notes

The KEDA example scales `dms-gpu-embedding-worker` from zero based on pending `CHUNKING` and `EMBEDDING` jobs in `dms_processingjob`. It intentionally uses a placeholder Secret reference and does not include real credentials.

Use separate ScaledObjects per worker class if queue pressure differs by role. Keep `maxReplicaCount` conservative until backpressure and processing profile limits are validated with real documents.

## Healthchecks

- Web readiness/liveness uses HTTP `GET /health/`.
- Scheduler and workers use `python manage.py processing_role_healthcheck --role <role>`.
- Qdrant health remains optional through `HEALTH_CHECK_QDRANT`; do not enable it unless Qdrant is expected to be reachable from the pod.
