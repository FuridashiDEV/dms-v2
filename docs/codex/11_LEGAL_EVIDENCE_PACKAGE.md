# 11_LEGAL_EVIDENCE_PACKAGE.md

# ПУНКТ 11 — LEGAL EVIDENCE PACKAGE: ЮРИДИЧЕСКИЙ ПАКЕТ ДОКАЗАТЕЛЬНОСТИ

## Цель

Цель этого пункта — добавить export доказательной истории документа.

После предыдущих пунктов в системе уже должны существовать или частично существовать:

- Document;
- DocumentVersion;
- SHA-256 checksum;
- AuditEvent;
- ProcessingJob;
- ExtractedField;
- WorkflowInstance;
- WorkflowAction;
- Counterparty;
- DocumentExchange;
- ExchangeEvent.

Теперь нужно собрать эти данные в единый структурированный пакет.

Первый формат — JSON.

PDF-отчёт можно добавить позже.

## Главный принцип

Legal Evidence Package не должен создавать новую бизнес-логику.

Он должен только собирать уже существующие данные:

```text
Document
↓
DocumentVersion
↓
AI validation
↓
Workflow
↓
B2B Exchange
↓
AuditEvent
↓
Evidence JSON export