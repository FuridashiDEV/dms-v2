# Stage 30 — Webhook Delivery / Отправка внешних уведомлений

## Цель этапа

Довести существующую очередь webhook delivery до реальной отправки уведомлений во внешние системы.

Сейчас есть foundation: WebhookEndpoint и WebhookDelivery. Нужно добавить безопасную отправку.

## Что добавить

- webhook sender service;
- request signing;
- retry policy;
- delivery status;
- error logging;
- max attempts;
- manual retry action через admin или service;
- timeout;
- secret redaction.

## Как должно работать

Когда создаётся UsageEvent или другое поддерживаемое событие:

1. Создаётся WebhookDelivery.
2. Sender отправляет POST на endpoint.
3. В delivery сохраняется статус.
4. При ошибке увеличивается attempts.
5. После max attempts доставка помечается failed.
6. Секреты не пишутся в payload/logs.

## Безопасность

Webhook secret хранится только как hash или безопасная ссылка на секрет.

В payload нельзя включать:

- secure tokens;
- passwords;
- API keys;
- webhook secrets;
- portal URLs with token.

## Чего нельзя делать

- Не добавлять полноценный public API.
- Не делать бесконечные retries.
- Не блокировать основной пользовательский процесс из-за ошибки webhook.
- Не начинать Stage 31.

## Тесты

Добавить tests:

1. Delivery отправляется на endpoint.
2. Successful response marks delivery as delivered.
3. Failed response increments attempt.
4. Max attempts marks failed.
5. Payload is sanitized.
6. Secret is not disclosed.

## Проверки

Выполнить:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
git diff --check
git status