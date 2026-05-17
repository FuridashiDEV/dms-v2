# Stage 45 Progress - Advanced Document Relation Graph

## Status

Completed.

Stage file read: `docs/codex/45_ADVANCED_DOCUMENT_RELATION_GRAPH.md`.

Note: the local stage file is truncated after the relation-chain UI example, so implementation followed the available file text and explicit user requirements.

Stage 46 was not started.

## Implemented

- Extended existing `DocumentRelation`; no separate relation/document system was created.
- Added relation types:
  - `CONTRACT_TO_APPENDIX`;
  - `CONTRACT_TO_INVOICE`;
  - `CONTRACT_TO_ACT`;
  - `CONTRACT_TO_ADDITIONAL_AGREEMENT`;
  - `PARENT_CHILD`;
  - `DUPLICATE`;
  - `REFERENCES`;
  - `SAME_COUNTERPARTY`;
  - `SAME_PROJECT`.
- Preserved existing Stage 20 relation types and flows.
- Added relation metadata:
  - `source`;
  - `confidence`;
  - `is_confirmed`;
  - `created_by`;
  - existing `created_at`.
- Added relation source choices:
  - `MANUAL`;
  - `SYSTEM_SUGGESTION`;
  - `AI_SUGGESTION`;
  - `IMPORTED`.
- Manual relation creation now stores:
  - source `MANUAL`;
  - `is_confirmed=True`;
  - `created_by=<current user>`.
- Added relation graph service functions in `dms/services/document_relations.py`:
  - `build_document_relation_graph`;
  - `suggest_document_relations`;
  - `infer_relation_type`.
- Added graph-chain foundation for accessible relation paths such as:
  - contract -> appendix -> act -> invoice.
- Added auto-discovery suggestions without auto-confirmation:
  - suggestions are returned as transient service results;
  - they are not persisted automatically;
  - they do not change official document fields.
- Added search integration hardening:
  - related-document search boost now uses only confirmed relations;
  - unconfirmed/system/AI suggestions are excluded from related search candidates;
  - related results remain filtered by `get_allowed_documents`.
- Extended document detail page:
  - relation graph summary;
  - accessible chain display;
  - relation source/confidence/confirmation metadata;
  - suggested relation confidence and reasons.
- Extended Django admin for relation source, confirmation, creator and filters.
- Extended relation form choices to include the new advanced relation types.

## Access and isolation

- Relation graph uses `get_allowed_documents(user)` and same-organization filtering.
- Inaccessible documents are not included in graph nodes, graph edges, suggestions or search related results.
- Cross-organization documents are still blocked by existing relation service validation.
- AI/system suggestions are not confirmed automatically and are not used as confirmed search graph edges.

## Changed files

- `dms/models.py`
- `dms/migrations/0041_advanced_document_relation_graph.py`
- `dms/admin.py`
- `dms/forms.py`
- `dms/services/document_relations.py`
- `dms/services/search_experience.py`
- `dms/views.py`
- `templates/dms/document_detail.html`
- `dms/test_advanced_document_relation_graph_stage45.py`
- `docs/codex/progress/STAGE_45_PROGRESS.md`

## Migrations

- Added `dms/migrations/0041_advanced_document_relation_graph.py`.
- Migration adds `source`, `is_confirmed`, `created_by`, widens `relation_type` to 40 chars, and adds an index on `(source, is_confirmed)`.
- Applied locally with `python manage.py migrate`.

## Checks run

- `git fetch --all --prune` - passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --name advanced_document_relation_graph dms` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms.test_advanced_document_relation_graph_stage45 dms.test_related_documents dms.test_search_experience_stage26 --verbosity 1` - 15 tests passed.
- `.\.venv\Scripts\python.exe manage.py check` - passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` - passed, no changes detected.
- `.\.venv\Scripts\python.exe manage.py migrate --check` - initially failed before applying the new migration, then passed after `migrate`.
- `.\.venv\Scripts\python.exe manage.py migrate` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms --verbosity 1` - 229 tests passed.

## Expected test/runtime warnings

- Full suite printed existing expected warnings for negative permission/404 tests.
- Full suite printed existing expected Qdrant unavailable warnings because local Qdrant is not running.
- Stage 45 does not require Qdrant.

## Manual verification checklist

- Open a contract detail page and add a manual relation to an appendix/act/invoice.
- Confirm relation source is `MANUAL`, confirmed state is true, and creator appears in admin.
- Open the related document and confirm reverse relation remains visible.
- Create a chain contract -> appendix -> act -> invoice and verify relation graph summary appears.
- Confirm a user without access to a related document cannot see it in relation graph, suggestions or search results.
- Confirm suggestions are displayed as suggestions only and do not create `DocumentRelation` rows until manually added.
- Search for a contract and verify confirmed related documents can appear, while unconfirmed AI/system suggestions do not boost search.

## Limitations / next-stage notes

- The graph UI is a readable foundation, not a full interactive graph canvas.
- Suggestions use deterministic metadata/title/entity heuristics; no new AI model was added.
- There is no separate suggestion approval queue yet; suggestions are transient on document detail.
- Stage 46 was not started.
