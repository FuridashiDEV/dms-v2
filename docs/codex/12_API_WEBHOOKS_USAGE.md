# 12_API_WEBHOOKS_USAGE.md

# ПУНКТ 12 — API / WEBHOOKS / USAGE TRACKING

## Цель

Цель этого пункта — добавить основу для API, webhooks и учёта использования продукта.

После предыдущих пунктов система уже должна уметь:

- хранить документы;
- работать с организациями;
- версионировать документы;
- записывать AuditEvent;
- обрабатывать AI-поля;
- импортировать документы;
- запускать workflow;
- обмениваться документами с контрагентами;
- экспортировать evidence package.

Теперь нужно добавить слой, который позволит:

- считать usage по organization;
- в будущем строить тарифы и billing;
- отправлять события во внешние системы;
- подготовить базовый API для интеграций.

## Главный принцип

Этот пункт не должен менять основную бизнес-логику DMS.

Usage tracking и webhooks должны быть дополнительным слоем поверх существующих действий.

Правильная логика:

```text
document uploaded
↓
existing business logic works
↓
UsageEvent is recorded
↓
AuditEvent remains independent
↓
Webhook can be queued/sent if configured