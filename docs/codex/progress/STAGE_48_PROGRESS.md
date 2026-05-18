# Stage 48 Progress - AI Search UX Layer

## Status

Completed.

Stage file read: `docs/codex/48_AI_SEARCH_UX_LAYER.md`.

Stage 49 was not started.

## Implemented

- Added AI search UX helpers in `dms/services/search_experience.py`:
  - search mode explanations for hybrid, exact and semantic modes;
  - human-readable confidence labels;
  - search readiness badges;
  - safe search suggestions;
  - accessible similar-document lookup.
- Updated `document_list` search flow:
  - keeps existing Stage 25-37 search core unchanged;
  - adds readiness metadata per visible result;
  - adds confidence metadata per ranked result;
  - adds accessible similar documents;
  - adds search suggestions and active filter summary to template context.
- Updated `templates/dms/document_list.html`:
  - search mode education;
  - search suggestions;
  - readiness indicators;
  - confidence UI without claiming exact mathematical accuracy;
  - related and similar documents sections;
  - improved empty state with applied filters and indexing/readiness hint.
- Added focused Stage 48 tests.

## Readiness UI

Displayed statuses are derived from existing document/index state:

- uploaded;
- basic search ready;
- text extracted;
- semantic indexing pending;
- semantic search ready;
- processing failed.

The UI does not expose raw Qdrant payload, point IDs or internal vector metadata.

## Confidence UI

Confidence is displayed as:

- high confidence;
- medium confidence;
- low confidence;
- not scored.

The UI intentionally avoids exact percentage/precision claims.

## Search suggestions

Suggestions can guide users to:

- search by detected counterparty;
- search around detected amount;
- search by detected document type;
- try alias variants;
- use generic business-search examples when no structured query is available.

Suggestions are generated from the parsed query and safe filter params only.

## Similar documents

Similar documents are shown only from the existing `get_allowed_documents(user)` scope.

Signals used:

- same counterparty entity;
- same document type entity;
- same `Document.doc_type`;
- overlapping key phrases.

Documents from another organization or without access are not included.

## Changed files

- `dms/services/search_experience.py`
- `dms/views.py`
- `templates/dms/document_list.html`
- `dms/test_ai_search_ux_stage48.py`
- `docs/codex/progress/STAGE_48_PROGRESS.md`

## Migrations

- No migrations were added.
- No models were changed.

## Checks run

- `git fetch --all --prune` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms.test_ai_search_ux_stage48 --verbosity 2` - 4 tests passed.
- `.\.venv\Scripts\python.exe manage.py check` - passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` - passed, no changes detected.
- `.\.venv\Scripts\python.exe manage.py migrate --check` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms --verbosity 1` - 247 tests passed.

## Expected test/runtime warnings

- Full suite printed existing expected warnings for negative permission/404 tests.
- Full suite printed expected `/health/` service-unavailable test output.
- Full suite printed expected Qdrant unavailable warnings because local Qdrant is not running.
- Full suite printed an HF Hub unauthenticated warning while loading local embedding dependencies.

## Manual verification checklist

- Open the document list/search page.
- Confirm hybrid is the default search mode and mode descriptions are readable.
- Search a business query such as `contract IP Firma tools 3 mln`.
- Confirm result cards show readiness badges.
- Confirm result cards show high/medium/low/not-scored confidence labels, not exact percentages.
- Confirm snippets, matched entities and explanations remain visible.
- Confirm related documents are shown only when accessible.
- Confirm similar documents are shown only when accessible.
- Search for a missing phrase and confirm empty state shows applied filters and practical suggestions.
- Stop Qdrant locally and confirm search still degrades safely without exposing raw vector payload.

## Limitations / next-stage notes

- Similar-document matching is deterministic and conservative; it is not a full recommendation engine.
- Confidence is a UX label derived from existing search ranking signals, not a legal or mathematical guarantee.
- The search page still inherits older mixed-language/mojibake copy in parts of the existing template.
- No raw Qdrant payload or inaccessible documents are exposed.
