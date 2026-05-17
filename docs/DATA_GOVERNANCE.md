# Data Governance Baseline

This document describes the current governance foundation. It is not a legal certification, SOC2/ISO statement, or automated retention policy.

## Scope

The foundation covers:

- sensitive entity detection for documents and AI processing;
- AI processing privacy rules;
- access audit hardening;
- retention policy records;
- operational manual checks for governance-sensitive flows.

## Sensitive Entities

The system can detect and store safe references for:

- IIN-like 12 digit identifiers;
- BIN-like 12 digit identifiers when the surrounding text indicates BIN;
- phone numbers;
- email addresses;
- monetary amounts;
- explicit personal-name patterns such as `FIO:` or `ФИО:`.

Raw sensitive values are not stored in `SensitiveEntity`. The stored record contains:

- organization;
- optional document;
- entity type;
- SHA-256 hash of normalized raw value;
- masked value;
- confidence;
- source;
- safe context.

## AI Privacy Rules

AI processing must not log or store in operational metadata:

- full document text;
- raw extracted text;
- file paths;
- secure tokens;
- API keys;
- passwords;
- authorization headers;
- raw Qdrant payload.

Processing metadata should use document ids, public ids, checksum, text length and entity counts instead of raw content. AI suggestions remain reviewable and must not be applied to official `Document` fields without user confirmation.

## Access Audit

The audit trail records key access events:

- document detail view;
- protected file view;
- protected file download;
- version view/download;
- search execution;
- counterparty exchange;
- evidence export/report view.

Search audit metadata stores safe operational fields only, such as mode, result count, search text length and entity-key names. It must not store the raw search query or full document content.

## Retention Foundation

`RetentionPolicy` records define review windows for:

- documents;
- document versions;
- audit events;
- processing results;
- temporary files.

Current policy action is foundation-level. The system does not automatically delete records or files without explicit implementation and approval of a concrete deletion workflow.

## Manual Review Checklist

- Confirm sensitive records contain masked values and hashes only.
- Confirm audit metadata does not include raw query text, document body text, tokens, passwords or file paths.
- Confirm AI processing jobs store text length and safe counts, not full text.
- Confirm retention policies exist for the organization or global defaults.
- Confirm legal hold and business retention requirements are reviewed before any future deletion automation.

## Limitations

- Sensitive entity detection is regex/foundation based and is not guaranteed to find every PII instance.
- Personal-name detection is intentionally conservative to reduce false positives.
- Retention policies do not enforce deletion automatically.
- This baseline is not a legal, regulatory, SOC2 or ISO certification.
