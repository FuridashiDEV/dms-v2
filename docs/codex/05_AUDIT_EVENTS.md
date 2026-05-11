# 05_AUDIT_EVENTS.md

# ПУНКТ 5 — AUDIT EVENT: СИСТЕМНЫЙ ЖУРНАЛ СОБЫТИЙ

## Цель

Цель этого пункта — добавить системный audit trail для действий с документами.

AuditEvent нужен для:

- контроля действий пользователей;
- расследования ошибок;
- enterprise security;
- будущего workflow;
- будущего counterparty portal;
- будущего B2B exchange;
- будущего legal evidence package.

Важно:

`AuditEvent` не заменяет `DocumentActivity`.

`DocumentActivity` остаётся для текущей пользовательской активности, recent activity, dashboard и привычной логики проекта.

`AuditEvent` — это более строгий системный журнал.

## Главный принцип

Не ломать текущую активность документов.

Нужно добавить AuditEvent поверх существующей системы:

```text
DocumentActivity — пользовательская активность
AuditEvent — системный / юридический / security-журнал