# Stage 39 Progress - Kubernetes AI Orchestration

## Status

Completed.

Stage file read: `docs/codex/39_KUBERNETES_AI_ORCHESTRATION.md`.

Note: the local stage file is truncated after the `deploy/k8s/` section start, so implementation followed the available file text and explicit user requirements.

## Implemented

- Added Kubernetes-ready separation for processing roles:
  - `web`
  - `scheduler`
  - `ocr-worker`
  - `embedding-worker`
  - `entity-worker`
  - `rerank-worker`
  - `qdrant-index-worker`
  - `notification-worker`
- Added `dms/services/processing_roles.py` with explicit role-to-ProcessingJob-stage mapping.
- Extended processing queue drain to support stage filtering while preserving Stage 38 behavior and profile backpressure.
- Added management commands:
  - `run_processing_role` for long-running scheduler/worker containers and `--once` smoke checks.
  - `processing_role_healthcheck` for worker/scheduler liveness and readiness probes.
- Added Kubernetes template foundation in `deploy/k8s/`:
  - namespace;
  - ConfigMap;
  - placeholder Secret example;
  - web Deployment and Service;
  - scheduler Deployment;
  - CPU worker Deployments;
  - GPU embedding worker Deployment template;
  - KEDA ScaledObject example;
  - README with role, KEDA, local-mode and healthcheck notes.
- Added resource request/limit examples for web, scheduler, CPU workers and GPU worker.
- Added GPU worker template with `nvidia.com/gpu: "1"` requests/limits and node/toleration examples.
- Added KEDA-compatible PostgreSQL queue depth scaling example.
- Kept Docker Compose and local runtime unchanged.
- Did not add real secrets.
- Did not require a real Kubernetes cluster.

## Upload/search/local safety

- `docker-compose.yml` was not changed.
- Dockerfile local/web command was not changed.
- Existing `/health/` remains the web health endpoint.
- Worker commands use existing Stage 38 `ProcessingJob` and `processing_center` services.
- `qdrant-index-worker` uses the existing local indexing service path; no GPU center writes directly to Qdrant.
- Stage 40 was not started.

## Changed files

- `dms/services/processing_center.py`
- `dms/services/processing_roles.py`
- `dms/management/commands/run_processing_role.py`
- `dms/management/commands/processing_role_healthcheck.py`
- `dms/test_kubernetes_ai_orchestration_stage39.py`
- `deploy/k8s/namespace.yaml`
- `deploy/k8s/configmap.yaml`
- `deploy/k8s/secret.example.yaml`
- `deploy/k8s/web.yaml`
- `deploy/k8s/scheduler.yaml`
- `deploy/k8s/workers.yaml`
- `deploy/k8s/gpu-worker.yaml`
- `deploy/k8s/keda-scaledobject.example.yaml`
- `deploy/k8s/README.md`
- `docs/codex/progress/STAGE_39_PROGRESS.md`

## Migrations

No migrations were created.

## Checks run

- `.\.venv\Scripts\python.exe manage.py test dms.test_kubernetes_ai_orchestration_stage39 --verbosity 2` - failed once while refining global worker drain behavior.
- `.\.venv\Scripts\python.exe manage.py test dms.test_kubernetes_ai_orchestration_stage39 dms.test_processing_center_stage38 --verbosity 1` - 12 tests passed.
- `.\.venv\Scripts\python.exe manage.py check` - passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` - passed.
- `.\.venv\Scripts\python.exe manage.py migrate --check` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms --verbosity 1` - 200 tests passed.

## Manual verification checklist

- Review `deploy/k8s/secret.example.yaml` and replace placeholders through the target cluster secret mechanism before applying manifests.
- Review and replace image references in all manifests for the deployment registry/tag.
- Confirm target cluster has PostgreSQL, Redis and Qdrant network addresses matching `configmap.yaml`.
- If GPU workers are enabled, confirm NVIDIA device plugin, node labels and tolerations match the actual cluster.
- If KEDA is enabled, confirm the PostgreSQL scaler and TriggerAuthentication are installed and point to the target database safely.
- Smoke check workers locally without Kubernetes:
  - `python manage.py processing_role_healthcheck --role embedding-worker --skip-db`
  - `python manage.py run_processing_role --role entity-worker --once --limit 1`
- Confirm Docker Compose local mode still starts through `docker compose up --build`.

## Limitations / next-stage notes

- This is Kubernetes-ready foundation only; no real cluster deployment was performed.
- No Helm, Terraform or Kubernetes operator was added.
- `notification-worker` is healthcheck-ready but has no `ProcessingJob` stages yet.
- KEDA scaling is an example and should be tuned against real queue depth, worker latency and database load.
- Resource requests/limits are starting examples, not capacity planning guarantees.
