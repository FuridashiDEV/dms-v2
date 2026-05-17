# Stage 35 - Advanced Entity Extraction

## Status

Completed.

## Stage File

Read: `docs/codex/35_ADVANCED_ENTITY_EXTRACTION.md`.

## Scope

Stage 35 strengthened entity extraction for documents and search queries without changing the search core architecture, without adding database models or migrations, and without changing AI review behavior. Extracted entities are stored in the existing `Document.search_entities` JSON metadata and help search/ranking only. They do not automatically update official `Document` fields.

## Current Architecture Confirmed

- `DocumentEntity` model: not present.
- Entity storage: existing `Document.search_entities` JSON field.
- `ExtractedField`: present in `dms.models` and used by the AI review pipeline as editable/confirmable suggestions.
- Query parsing: `dms/services/search_intelligence.py`.
- Entity matching in search: `score_document_for_query()` and `matched_entities_for_document()`.
- Indexing: `dms/services/document_indexing.py`.

## Implemented

- Added `dms/services/entity_extraction.py`.
- Added typed entity extraction payload with confidence scores.
- Preserved Stage 25 compatibility keys:
  - `document_type`
  - `counterparty`
  - `subject`
  - `amount`
  - `key_phrases`
  - `aliases`
- Added structured `entities_by_type`.
- Added `entity_confidence` and `overall_confidence`.
- Added query entity extraction through the same service.
- Updated document search text assembly to include advanced entities.
- Updated entity index chunks to include advanced entity values.
- Updated lexical filtering and result matched-entity explanations for advanced entity fields.
- Added focused tests for extraction, table-aware foundation, search scoring, and AI review non-application.

## Entity Types Supported

- `document_type`
- `counterparty`
- `organization_name`
- `legal_form`
- `bin_iin`
- `amount`
- `currency`
- `document_number`
- `document_date`
- `contract_reference`
- `subject`
- `goods`
- `services`
- `works`
- `person`
- `position`
- `department`
- `related_document_hint`
- `table_item`
- `search_phrase`

## Extraction Coverage

- Amounts: supports compact values, thousands/millions, KZT/USD/EUR markers, and avoids treating BIN/IIN as money.
- Dates: supports `DD.MM.YYYY`, `DD/MM/YYYY`, `DD-MM-YYYY`, and `YYYY-MM-DD`, normalized to ISO.
- Document numbers: supports `No`, `#`, and document-label patterns.
- BIN/IIN: supports 12-digit values with BIN/IIN labels.
- Counterparty: supports labeled counterparties and common legal forms.
- Subject/goods/services/works: extracts business subject signals and product/service/work hints.
- Table-aware foundation: detects simple pipe/tab/semicolon table-like rows and stores them as `table_item` entities.

## AI Review Safety

No changes were made to `ExtractedField` workflow. Entity extraction does not create `ExtractedField` rows and does not apply any extracted values to official `Document` fields automatically.

## Changed Files

- `dms/services/entity_extraction.py`
- `dms/services/search_intelligence.py`
- `dms/services/document_indexing.py`
- `dms/services/search_experience.py`
- `dms/test_advanced_entity_extraction_stage35.py`
- `docs/codex/progress/STAGE_35_PROGRESS.md`

## Migrations

None. No model/schema changes were made.

## Checks Run

- `.\.venv\Scripts\python.exe manage.py test dms.test_advanced_entity_extraction_stage35 --verbosity 2` - passed, 5 tests.
- `.\.venv\Scripts\python.exe manage.py test dms.test_search_intelligence_stage25 --verbosity 1` - passed, 7 tests.
- `.\.venv\Scripts\python.exe manage.py check` - passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` - passed, no changes detected.
- `.\.venv\Scripts\python.exe manage.py migrate --check` - passed.
- `.\.venv\Scripts\python.exe manage.py test dms --verbosity 1` - passed, 176 tests.
- `git diff --check` - passed; only Git CRLF warnings were printed.
- `git status --short --branch` - reviewed.

## Manual Verification Checklist

- Upload/import a real contract-like document with counterparty, BIN/IIN, amount, date, and document number.
- Reindex the document.
- Search by counterparty and amount.
- Search by document number.
- Search by BIN/IIN.
- Search by a table line item or goods/services phrase.
- Confirm search explanations show matched entities where applicable.
- Confirm AI review still requires manual approval before any official document metadata changes.
- Confirm documents from another organization or without access are not returned.

## Known Limitations

- Extraction is deterministic regex/rule based; it improves business search signals but does not guarantee perfect entity recognition.
- Table support is a foundation for simple text/table-like rows, not a full spreadsheet or PDF table parser.
- Extracted entities are normalized search metadata, not legally authoritative document attributes.

## Stage 36

Not started.
