# Stage 23 — Усиление B2B-обмена

Дата: 2026-05-13
Ветка: `stage-23-b2b-exchange-maturity`
Статус: completed

## Цель

Усилить существующий B2B exchange вокруг текущих `DocumentExchange`, `ExchangeEvent`, `ExchangeMessage`, `Counterparty` и `CounterpartyContact` без создания отдельной системы обмена, внешних аккаунтов или real-time чата.

## Что изменено

- Добавлена карточка exchange: `/exchanges/<id>/`.
- Добавлены internal actions:
  - revoke secure link;
  - reissue/resend secure link с новым token hash и сроком действия.
- Exchange list теперь ведет в карточку exchange и показывает активность ссылки.
- Document detail теперь содержит ссылку на карточку exchange.
- Portal для revoked/expired links показывает безопасное сообщение без раскрытия названия документа в видимой карточке и без download action.
- Download через revoked/expired token возвращает 404.
- Expired/revoked exchange events теперь пишут audit events:
  - `EXCHANGE_EXPIRED`;
  - `EXCHANGE_REVOKED`.
- Internal message form доступна из карточки exchange и сохраняет сообщения в существующий `ExchangeMessage`.
- Добавлены свойства `DocumentExchange.is_link_expired`, `DocumentExchange.is_link_active`, `DocumentExchange.last_downloaded_at`.

## Миграции

Добавлена миграция:

- `dms/migrations/0034_exchange_maturity_audit_events.py`

Миграция только расширяет choices поля `AuditEvent.event_type`.

## Проверки

Выполнено:

```powershell
.\.venv\Scripts\python.exe manage.py test dms.test_b2b_exchange_maturity --verbosity 2
.\.venv\Scripts\python.exe manage.py test dms.test_counterparty_portal_mvp dms.test_b2b_document_exchange dms.test_b2b_communication_layer --verbosity 1
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
git diff --check
```

Результат:

- Stage 23 targeted tests — 4 OK.
- Existing B2B/portal tests — 12 OK.
- `manage.py check` — OK.
- `makemigrations --check --dry-run` — no changes detected.
- `migrate` — applied `dms.0034_exchange_maturity_audit_events`.
- `migrate --check` — OK after applying migration locally.
- Full `dms` suite — 112 tests OK.
- `git diff --check` — OK, only expected CRLF warnings on Windows.

## Ручная проверка

1. Login as internal user with access to a document.
2. Open document detail and create outgoing counterparty exchange.
3. Open B2B Exchanges list.
4. Open exchange card from the list.
5. Verify visible fields: document, direction, counterparty, contact, status, sent/opened/downloaded/responded dates, expiration, link active state.
6. Add internal message from exchange card.
7. Revoke link and verify:
   - exchange status becomes revoked;
   - ExchangeEvent exists;
   - AuditEvent exists;
   - portal token shows safe unavailable message;
   - download through token returns 404.
8. Resend/reissue link and verify:
   - same exchange receives new token hash/hint;
   - old token no longer works;
   - new token opens portal;
   - SENT event and audit are recorded.
9. Create expired exchange or wait for expiration and verify portal/download behavior.
10. Login as user from another organization and verify exchange card is not accessible.

## Ограничения

- No external counterparty accounts were added.
- No separate exchange system was created.
- No real-time chat/WebSocket was added.
- Resend reissues the secure token on the existing outgoing `DocumentExchange`; accepted exchanges cannot be resent.
- Stage 24 was not started.
