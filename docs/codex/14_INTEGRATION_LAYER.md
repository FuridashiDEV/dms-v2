# 14_INTEGRATION_LAYER.md

# ПУНКТ 14 — INTEGRATION LAYER: ПОДГОТОВКА ИНТЕГРАЦИЙ С ВНЕШНИМИ СИСТЕМАМИ

## Цель

Цель этого пункта — добавить foundation для будущих интеграций с внешними системами клиента.

После предыдущих пунктов система уже должна уметь:

- хранить документы;
- работать с организациями;
- версионировать документы;
- записывать AuditEvent;
- обрабатывать AI-поля;
- импортировать документы;
- запускать workflow;
- обмениваться документами с контрагентами;
- экспортировать evidence package;
- считать usage;
- иметь security baseline.

Теперь нужно подготовить слой интеграций.

Важно: на этом пункте не нужно полноценно реализовывать все интеграции.

Нужно создать архитектуру, чтобы позже безопасно подключать:

- email ingestion;
- 1C import/export;
- Google Drive;
- OneDrive;
- SharePoint;
- DocuSign / Adobe Sign;
- локальную ЭЦП;
- ERP;
- API-based external systems.

## Главный принцип

Integration Layer не должен создавать отдельную систему документов.

Любой внешний файл или внешний документ должен в итоге быть связан с существующим `Document`.

Правильная логика:

```text
External system
↓
IntegrationConnection
↓
SyncJob
↓
ExternalReference
↓
Existing Document
↓
AI / Workflow / Exchange / Evidence