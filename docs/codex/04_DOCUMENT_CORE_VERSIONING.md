# 04_DOCUMENT_CORE_VERSIONING.md

# ПУНКТ 4 — DOCUMENT CORE 2.0: ВЕРСИИ, СТАТУСЫ, HASH

## Цель

Цель этого пункта — усилить существующую модель Document, не ломая текущую систему.

После этого пункта документ должен быть не просто загруженным файлом, а управляемым объектом с:

- текущим статусом;
- историей версий;
- SHA-256 hash файла;
- связью с organization;
- сохранением обратной совместимости со старым `Document.file`.

Этот пункт является технической основой для следующих этапов:

- AuditEvent;
- AI Processing Pipeline;
- Workflow;
- Counterparty Portal;
- Legal Evidence Package.

## Главный принцип

Не переписывать Document с нуля.

Не удалять существующее поле `file`.

Не ломать текущий upload flow.

Нужно нарастить текущую модель Document:

```text
старый Document
↓
Document + status
↓
Document + DocumentVersion
↓
Document + checksum
↓
старые функции продолжают работать