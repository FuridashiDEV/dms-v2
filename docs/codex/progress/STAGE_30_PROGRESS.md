# Stage 30 — Webhook Delivery / Отправка внешних уведомлений

Дата: 2026-05-17
Ветка: `stage-30-webhook-delivery`
Статус: completed

## Прочитанный stage-файл

- `docs/codex/30_WEBHOOK_DELIVERY.md`

## Что реализовано

- Добавлен service-layer `dms.services.webhooks` для безопасной отправки существующих `WebhookDelivery`.
- Используются существующие модели:
  - `WebhookEndpoint`;
  - `WebhookDelivery`;
  - `UsageEvent`.
- Добавлена отправка POST на endpoint через стандартную библиотеку Python без тяжёлых зависимостей.
- Добавлена HMAC SHA-256 request signing при наличии runtime secret.
- Добавлены headers:
  - `X-DMS-Event`;
  - `X-DMS-Delivery-ID`;
  - `X-DMS-Timestamp`;
  - `X-DMS-Signature`, если signing secret доступен и соответствует `secret_hash`.
- Добавлена retry policy:
  - `attempt_count` увеличивается при каждой попытке;
  - 2xx response помечает delivery как `SENT`;
  - non-2xx response оставляет `PENDING` до max attempts;
  - после max attempts delivery становится `FAILED`;
  - `next_attempt_at` рассчитывается через exponential backoff.
- Добавлен timeout.
- Добавлен secret redaction для ошибок.
- Payload дополнительно sanitizes before delivery.
- Добавлена management command `deliver_webhooks`.
- Добавлен admin action `Retry selected webhook deliveries`.
- Добавлены focused tests для Stage 30.

## Как работает webhook delivery

1. Product flow создаёт `UsageEvent`.
2. Существующий usage service создаёт `WebhookDelivery` для активных endpoint той же organization.
3. Пользовательский flow на этом заканчивается: webhook не отправляется синхронно внутри основного действия.
4. Отправка выполняется отдельно:

```powershell
.\.venv\Scripts\python.exe manage.py deliver_webhooks --limit 100
```

5. Для одной delivery:

```powershell
.\.venv\Scripts\python.exe manage.py deliver_webhooks --delivery-id <id>
```

6. Sender берёт pending delivery, sanitizes payload, подписывает request при наличии runtime secret и отправляет POST.
7. Результат сохраняется в `WebhookDelivery`:
   - `status`;
   - `attempt_count`;
   - `response_status`;
   - `last_error`;
   - `next_attempt_at`.

## Signing secret

`WebhookEndpoint.secret_hash` остаётся hash, а не plaintext secret.

Runtime secret можно передать через:

- `settings.DMS_WEBHOOK_SIGNING_SECRETS`, ключ `endpoint.id` или `endpoint.name`;
- environment variable `DMS_WEBHOOK_SECRET_<endpoint_id>`;
- environment variable по имени endpoint: `DMS_WEBHOOK_SECRET_<ENDPOINT_NAME>`.

Если secret не найден или его hash не совпадает с `secret_hash`, подпись не добавляется.

## Secret redaction и payload safety

Перед отправкой удаляются sensitive keys:

- `token`;
- `secret`;
- `api_key`;
- `apikey`;
- `password`;
- `private_key`;
- `authorization`.

Ошибки транспорта сохраняются в `last_error` с redaction. Webhook secrets, API keys и passwords не пишутся в payload/logs.

## Изменённые файлы

- `dms/services/webhooks.py`
- `dms/management/commands/deliver_webhooks.py`
- `dms/test_webhook_delivery_stage30.py`
- `dms/admin.py`
- `docs/codex/progress/STAGE_30_PROGRESS.md`

## Миграции

Новых миграций нет. Использованы существующие поля `WebhookEndpoint` и `WebhookDelivery`.

## Проверки

Выполнено:

```powershell
.\.venv\Scripts\python.exe manage.py test dms.test_webhook_delivery_stage30 --verbosity 2
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
git diff --check
git status --short --branch
```

Результаты:

- Stage 30 focused tests: 6 OK.
- `manage.py check`: OK.
- `makemigrations --check --dry-run`: no changes detected.
- `migrate --check`: OK.
- Full `dms` suite: 149 tests OK.
- `git diff --check`: OK, only expected CRLF warnings on Windows.
- `git status --short --branch`: Stage 30 files present; unrelated pre-existing `docs/codex` deletions/untracked stage files remain unstaged.
- Full suite emitted existing warnings for unavailable local Qdrant and unauthenticated HuggingFace access; tests passed.

## Что нужно проверить вручную

1. Создать `WebhookEndpoint` для organization.
2. Указать event type, например `document.uploaded`, или оставить список пустым для всех событий.
3. Сохранить только `secret_hash`, plaintext secret держать вне БД.
4. Настроить runtime secret через env/settings.
5. Выполнить действие, создающее `UsageEvent`, и проверить появление `WebhookDelivery`.
6. Запустить `deliver_webhooks`.
7. Проверить, что внешняя система получила POST.
8. Проверить headers, signature, status, attempts и response status.
9. Проверить, что секреты не попадают в payload, logs или `last_error`.
10. Проверить ручной retry через Django admin action.

## Ограничения

- Полноценный public API не добавлялся.
- Бесконечные retries не добавлялись.
- Основной пользовательский flow не блокируется отправкой webhook.
- Stage 31 не начинался.
