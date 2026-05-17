# Load Testing Foundation

Stage 43 adds synthetic load-testing foundations for large DMS archives without using real customer documents.

The default mode is dry-run. Heavy database writes are not executed unless `--execute` is passed, and large runs require `--allow-heavy`.

## Profiles

| Profile | Documents | Purpose |
| --- | ---: | --- |
| `10k` | 10,000 | Small enterprise archive |
| `100k` | 100,000 | Large department archive |
| `500k` | 500,000 | Multi-department historical archive |
| `1m` | 1,000,000 | Million-scale archive planning |

## Dry Run

Generate a JSON report without database writes:

```powershell
.\.venv\Scripts\python.exe manage.py run_load_profile --profile 10k --dry-run
```

Dry-run reports include:

- synthetic document type distribution;
- RU/KZ sample texts;
- OCR-like noise samples;
- estimated upload/processing/search/storage metrics;
- queue overload plan;
- safety flags.

## Small Execute Smoke Test

Create a small synthetic dataset:

```powershell
.\.venv\Scripts\python.exe manage.py run_load_profile --profile 10k --execute --limit 100
```

This creates ordinary `Document` and `DocumentVersion` rows under organization `load-test-synthetic`. File fields reference synthetic names under `load-test/<organization>/...`; no real customer files are used.

## Queue Overload Foundation

Create a small synthetic processing backlog:

```powershell
.\.venv\Scripts\python.exe manage.py run_load_profile --profile 10k --execute --limit 100 --include-queue --queue-jobs 200
```

The queue portion creates `ProcessingJob` records for controlled backpressure/retry/failed-job checks. It does not run the workers.

## Heavy Runs

Large execute runs are blocked by default:

```powershell
.\.venv\Scripts\python.exe manage.py run_load_profile --profile 100k --execute
```

Use a controlled environment and explicit confirmation:

```powershell
.\.venv\Scripts\python.exe manage.py run_load_profile --profile 100k --execute --allow-heavy
```

Before heavy runs:

- use a disposable or approved load-test database;
- ensure media/storage policy is understood;
- capture baseline `/health/`, database size and queue counts;
- do not run against production customer data;
- keep Qdrant indexing/reindexing as a separate planned benchmark.

## Reports

Default reports are written to:

```text
reports/load-testing/
```

Use `--report` to write to a specific path:

```powershell
.\.venv\Scripts\python.exe manage.py run_load_profile --profile 10k --dry-run --report reports/load-testing/10k-dry-run.json
```

Reports are operational artifacts and should normally not be committed unless intentionally promoted as a baseline.

## Limitations

- This is a foundation, not a full distributed load test harness.
- Dry-run estimates are planning aids, not production capacity guarantees.
- The command does not automatically run Qdrant reindexing, OCR workers or search probes for million-scale profiles.
- Real throughput must be measured in an isolated environment with representative infrastructure.
