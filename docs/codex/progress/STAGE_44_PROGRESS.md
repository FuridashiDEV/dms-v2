# Stage 44 Progress - Enterprise Search Explainability

## Status

Completed.

Stage file read: `docs/codex/44_ENTERPRISE_SEARCH_EXPLAINABILITY.md`.

Note: the local stage file is truncated after the UI example, so implementation followed the available file text and explicit user requirements.

Stage 45 was not started.

## Implemented

- Added search explainability service in `dms/services/search_explainability.py`.
- Added structured explanation payload for each ranked search result:
  - `matched_entities`;
  - `matched_aliases`;
  - `matched_chunks`;
  - `matched_filters`;
  - `semantic_score`;
  - `entity_score`;
  - `final_score`;
  - `confidence`;
  - `human_readable_reasons`;
  - `candidate_sources`.
- Integrated explainability into the existing `document_list` search flow after candidate fusion/reranking.
- Preserved existing search modes, filters, Qdrant fallback behavior and final permission filtering.
- Added safe snippet/chunk explanation from existing `Document` fields only.
- Added sensitive value redaction for explanation text:
  - token;
  - secure token;
  - access/refresh token;
  - password;
  - API key;
  - authorization;
  - secret;
  - raw payload labels.
- Updated the search results UI to show a concise `Found because` block with:
  - top human-readable reasons;
  - final/confidence/semantic/entity scores;
  - matched aliases;
  - matched active filters;
  - short safe matched fragments.
- Added focused Stage 44 tests for service output, redaction, UI rendering and inaccessible vector-hit protection.

## Security / privacy constraints

- Qdrant payload is not passed to the UI explanation layer.
- Search explanations are built only for documents that survived `get_allowed_documents(user)` filtering.
- Inaccessible vector hits are not rendered and do not contribute visible explanation data.
- Secure tokens, secrets, passwords, API keys and payload labels are redacted from explanation strings.
- No documents from another organization are exposed through explanations.
- No new Stage 45 relation graph work was added.

## Changed files

- `dms/services/search_explainability.py`
- `dms/views.py`
- `templates/dms/document_list.html`
- `dms/test_enterprise_search_explainability_stage44.py`
- `docs/codex/progress/STAGE_44_PROGRESS.md`

## Migrations

No migrations were created.

## Checks run

- `git fetch --all --prune` - passed before branch creation.
- `.\.venv\Scripts\python.exe manage.py test dms.test_enterprise_search_explainability_stage44 --verbosity 2` - 4 tests passed.
- `.\.venv\Scripts\python.exe manage.py check` - passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` - passed, no changes detected.
- `.\.venv\Scripts\python.exe manage.py migrate --check` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms --verbosity 1` - 228 tests passed.
- `git diff --check` - passed with existing LF/CRLF warnings for touched files.
- `git status --short --branch` - checked.

## Expected test/runtime warnings

- Full suite printed existing expected warnings for negative permission/404 tests.
- Full suite printed expected Qdrant unavailable warnings because local Qdrant is not running.
- Full suite printed an HF Hub unauthenticated warning while loading local embedding dependencies.

## Manual verification checklist

- Open document list and run a hybrid search with a business query.
- Confirm each result shows a concise `Found because` explanation.
- Confirm matched aliases and entity/filter reasons are understandable to a business user.
- Confirm scores are shown as supporting signals, not as a promise of mathematical certainty.
- Run a semantic search while Qdrant is unavailable and confirm the page degrades safely.
- Confirm documents from another organization or inaccessible department do not appear in results or explanations.
- Confirm no secure portal token, webhook secret, API key, password, Qdrant payload or server path appears in the UI.

## Limitations / next-stage notes

- Explanations are deterministic and based on existing search signals; no model-based explanation generator was added.
- Matched chunks are short snippets from accessible `Document` fields, not raw Qdrant payload chunks.
- Confidence remains an operational ranking signal, not a legal or mathematical guarantee.
- Further relation-graph explanation belongs to Stage 45 and was intentionally not implemented here.
