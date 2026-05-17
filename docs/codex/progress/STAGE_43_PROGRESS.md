# Stage 43 Progress - Million-Scale Load Testing Foundation

## Status

Completed.

Stage file read: `docs/codex/43_MILLION_SCALE_LOAD_TESTING.md`.

Note: the local stage file is truncated after the example `run_load_profile --profile 10k --dry-run` command, so implementation followed the available file text and explicit user requirements.

Stage 44 was not started.

## Implemented

- Added load-testing service in `dms/services/load_testing.py`.
- Added synthetic document generator with:
  - contracts;
  - acts;
  - invoices;
  - appendices;
  - orders;
  - Russian and Kazakh text samples;
  - OCR-like text noise;
  - synthetic counterparty, subject, amount and date fields.
- Added load profiles:
  - `10k` - 10,000 documents;
  - `100k` - 100,000 documents;
  - `500k` - 500,000 documents;
  - `1m` - 1,000,000 documents.
- Added benchmark/report command:
  - `python manage.py run_load_profile --profile 10k --dry-run`
  - dry-run is the default mode when `--execute` is not provided.
- Added safe execute mode:
  - creates ordinary `Document` rows;
  - creates matching `DocumentVersion #1` rows;
  - uses organization `load-test-synthetic` by default;
  - writes synthetic file names under `load-test/<organization>/...`;
  - does not use real customer documents.
- Added queue overload foundation:
  - optional `--include-queue`;
  - creates synthetic `ProcessingJob` backlog for controlled backpressure/retry/failure checks;
  - does not start workers automatically.
- Added heavy-run guard:
  - execute mode refuses more than 1,000 documents unless `--allow-heavy` is passed.
- Added JSON report generation:
  - requested/created document counts;
  - document type distribution;
  - sample synthetic documents;
  - estimated storage growth;
  - upload/processing/search/queue benchmark sections;
  - safety metadata.
- Added `docs/LOAD_TESTING.md` with dry-run, small execute, queue overload and heavy-run guidance.
- Added `.gitignore` rule for runtime load-testing JSON reports.
- Added focused Stage 43 tests.

## Safety rules

- No heavy load test was run by default.
- No real documents or customer data are used.
- No Qdrant reindexing, OCR workers or semantic search benchmark is started automatically.
- No Stage 44 work was started.
- Runtime reports under `reports/load-testing/*.json` are ignored by git unless intentionally handled separately.

## Changed files

- `.gitignore`
- `dms/services/load_testing.py`
- `dms/management/commands/run_load_profile.py`
- `dms/test_million_scale_load_testing_stage43.py`
- `docs/LOAD_TESTING.md`
- `docs/codex/progress/STAGE_43_PROGRESS.md`

## Migrations

No migrations were created.

## Commands

Dry-run report:

```powershell
.\.venv\Scripts\python.exe manage.py run_load_profile --profile 10k --dry-run
```

Small execute smoke test:

```powershell
.\.venv\Scripts\python.exe manage.py run_load_profile --profile 10k --execute --limit 100
```

Queue overload foundation:

```powershell
.\.venv\Scripts\python.exe manage.py run_load_profile --profile 10k --execute --limit 100 --include-queue --queue-jobs 200
```

Heavy execution, only in an approved load-test environment:

```powershell
.\.venv\Scripts\python.exe manage.py run_load_profile --profile 100k --execute --allow-heavy
```

## Checks run

- `git fetch --all --prune` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms.test_million_scale_load_testing_stage43 --verbosity 2` - 6 tests passed.
- `.\.venv\Scripts\python.exe manage.py check` - passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` - passed, no changes detected.
- `.\.venv\Scripts\python.exe manage.py migrate --check` - passed.
- `.\.venv\Scripts\python.exe manage.py run_load_profile --profile 10k --dry-run --report "$env:TEMP\stage43-load-dry-run.json"` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms --verbosity 1` - 224 tests passed.

## Expected test/runtime warnings

- Full suite printed existing expected warnings for negative permission/404 tests.
- Full suite printed existing expected Qdrant unavailable warnings because local Qdrant is not running.
- Stage 43 did not require Qdrant.

## Manual verification checklist

- Run `python manage.py run_load_profile --profile 10k --dry-run` and inspect the JSON report.
- Confirm dry-run does not create `Document`, `DocumentVersion` or `ProcessingJob` records.
- Run a small isolated execute test with `--execute --limit 100`.
- Confirm created records belong to organization `load-test-synthetic`.
- Confirm no real uploaded files or customer documents are used.
- Run a small queue overload test with `--include-queue --queue-jobs 200`.
- Confirm processing backlog appears in admin/dashboard without running workers automatically.
- In a dedicated load-test environment, decide whether to run larger profiles with `--allow-heavy`.

## Limitations / next-stage notes

- Dry-run estimates are planning aids, not production capacity guarantees.
- The command does not automatically benchmark real OCR, embeddings, Qdrant insert or search probes at million scale.
- Reports are JSON artifacts; no dashboard visualization was added at this stage.
- Heavy runs should be done only on disposable or approved load-test infrastructure.
