# Stage 53 - Pilot Demo Dataset

## Status

Completed.

## What was added

- Expanded `prepare_demo_data` with additional synthetic pilot documents:
  - additional agreement in the contract chain;
  - medicine vertical supply contract;
  - business vertical invoice;
  - quasi-government mixed-language status report.
- Updated idempotency test counts.
- Added `docs/demo/DEMO_SCENARIO.md`.
- Added `docs/demo/DEMO_DATASET_README.md`.

## Demo data created

- Demo organization and users.
- Contract chain: contract -> appendix -> act -> invoice -> additional agreement.
- University, medicine, business and quasi-government examples.
- Versions, relations, workflow, exchange, messages, import batch, audit events, usage events and AI review suggestions.

## How to use

```powershell
.\.venv\Scripts\python.exe manage.py prepare_demo_data --skip-vectors
```

Use `demo_admin / DemoArchive2026!` for the primary demo.

## Safety

- No real personal data.
- No real customer documents.
- Demo email/domain values use safe synthetic examples.
- External token printed by the command is only for local demo use.

## Tests

- `dms.test_demo_data_command` passed after count update.
