# Stage 47 Progress - Cost Optimization Engine

## Status

Completed.

Stage file read: `docs/codex/47_COST_OPTIMIZATION_ENGINE.md`.

Stage 48 was not started.

## Implemented

- Added cost optimization models:
  - `ProcessingCostPolicy` for immediate, batch, hourly, nightly, manual, archive-only and priority routing policies;
  - `ProcessingCostEstimate` for per-document/job cost estimates;
  - `ProcessingCostQuota` for monthly quota foundation.
- Extended `UsageEvent.EventType` with report-only cost signals:
  - `ai.document_processed`;
  - `ocr.page_processed`;
  - `embedding.chunk_processed`;
  - `search.rerank_request`;
  - `ai.cost_unit`.
- Added `dms/services/cost_optimization.py`:
  - default cost policy creation;
  - default quota creation;
  - document page/chunk estimation;
  - smart OCR routing;
  - processing policy selection;
  - quota snapshot and warning calculation;
  - dashboard report builder.
- Integrated cost estimation into processing center enqueue flow:
  - new `ProcessingJob` records receive safe cost metadata;
  - estimation failures do not block job creation.
- Extended billing foundation plan quotas with AI/OCR/embedding/rerank/cost-unit report limits.
- Added Django admin registration for cost policies, estimates and quotas.
- Added cost dashboard route and template:
  - `/costs/`;
  - superuser can inspect active organizations;
  - organization admins are scoped to their own organizations.
- Added focused Stage 47 tests for cost estimation, OCR routing, usage events, quotas, dashboard permissions and processing job metadata.

## Cost model

The estimate currently tracks:

- document count;
- estimated page count;
- smart OCR decision;
- estimated chunk count;
- embedding model from settings;
- processing time placeholder;
- estimated cost units;
- recommended policy;
- route reason;
- quota snapshot.

The cost model is intentionally conservative and report-only. It is suitable for dashboarding, pilot monitoring and later policy tuning, but it does not claim exact provider billing accuracy.

## Processing policies

Supported policy types:

- `immediate`;
- `batch_30_min`;
- `hourly`;
- `nightly`;
- `manual`;
- `archive_only`;
- `priority`.

Policies can be global or organization-specific. Default policies are created safely when needed.

## Smart OCR routing

OCR is recommended when:

- the document has no extracted text;
- extracted text quality is low;
- metadata marks the document as scan/image;
- OCR was explicitly requested.

OCR routing is advisory at this stage and does not delete or block processing jobs.

## Quota foundation

Quota snapshots currently include:

- AI documents/month;
- OCR pages/month;
- embeddings/month;
- rerank requests/month;
- AI cost units/month.

The quota layer returns warning status and projected usage. It does not automatically block customers.

## Changed files

- `dms/admin.py`
- `dms/models.py`
- `dms/migrations/0043_cost_optimization_engine.py`
- `dms/services/billing.py`
- `dms/services/cost_optimization.py`
- `dms/services/processing_center.py`
- `dms/urls.py`
- `dms/views.py`
- `dms/test_cost_optimization_stage47.py`
- `templates/dms/cost_optimization_dashboard.html`
- `docs/codex/progress/STAGE_47_PROGRESS.md`

## Migrations

- Added `dms/migrations/0043_cost_optimization_engine.py`.
- Migration adds:
  - `ProcessingCostPolicy`;
  - `ProcessingCostEstimate`;
  - `ProcessingCostQuota`;
  - cost-related `UsageEvent` choices.
- Applied locally with `python manage.py migrate`.

## Checks run

- `git fetch --all --prune` - passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --name cost_optimization_engine dms` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms.test_cost_optimization_stage47 --verbosity 2` - 7 tests passed.
- `.\.venv\Scripts\python.exe manage.py check` - passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` - passed, no changes detected.
- `.\.venv\Scripts\python.exe manage.py migrate --check` - initially failed because Stage 47 migration was unapplied.
- `.\.venv\Scripts\python.exe manage.py migrate` - passed.
- `.\.venv\Scripts\python.exe manage.py migrate --check` - passed after local migration.
- `.\.venv\Scripts\python.exe manage.py test dms --verbosity 1` - 243 tests passed.

## Expected test/runtime warnings

- Full suite printed existing expected warnings for negative permission/404 tests.
- Full suite printed an expected `/costs/` forbidden warning in the employee permission test.
- Full suite printed expected Qdrant unavailable warnings because local Qdrant is not running.
- Full suite printed an HF Hub unauthenticated warning while loading local embedding dependencies.

## Manual verification checklist

- Open `/costs/` as a superuser and confirm the organization selector and cost summary render.
- Open `/costs/` as an organization admin and confirm only that admin's organizations are available.
- Confirm an employee receives forbidden access to `/costs/`.
- Create or enqueue processing for a sample document and confirm `ProcessingCostEstimate` is created.
- Confirm `ProcessingJob.center_metadata.cost_estimate` contains cost units, policy and route reason but no document text or secrets.
- Confirm default `ProcessingCostQuota` rows are report-only and do not block uploads or processing.
- Upload a scan-like document and verify OCR routing recommends OCR.
- Upload a text-rich document and verify OCR routing does not recommend OCR by default.

## Limitations / next-stage notes

- Cost units are internal estimates, not exact cloud/GPU invoices.
- OCR page/chunk estimates are heuristic until real page counters and provider telemetry are connected.
- Quotas are advisory and do not enforce blocking.
- Dashboard is an admin/reporting foundation, not a full cost-management console.
- No payment gateway, invoice generation or hard customer blocking was added.
- Stage 48 was not started.
