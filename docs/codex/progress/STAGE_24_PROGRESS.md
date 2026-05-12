# Stage 24 — Уведомления

Дата: 2026-05-13
Ветка: `stage-24-notifications`
Статус: completed

## Цель

Добавить базовые внутренние уведомления для пользователей DMS без внешних push/email-сервисов, массовых рассылок и передачи secure portal tokens.

## Что реализовано

- Добавлена модель `Notification`.
- Добавлен service-layer `dms.services.notifications`.
- Добавлена страница уведомлений: `/notifications/`.
- Добавлена отметка уведомления прочитанным: `/notifications/<id>/read/`.
- Добавлен счетчик непрочитанных уведомлений в верхнюю навигацию.
- Добавлен Django admin для `Notification`.
- Уведомления фильтруются по `recipient` и organization пользователя.
- Ссылки на документ/exchange показываются только если у пользователя есть доступ к связанному документу.
- Notification text sanitization удаляет secure portal paths и длинные token-like строки.
- Demo seed очищает уведомления demo organization при повторной подготовке demo data.

## Какие события создают уведомления

- `WORKFLOW_ASSIGNED`:
  - создается при старте workflow для первого согласующего;
  - создается при переходе workflow к следующему согласующему.
- `AI_REVIEW_READY`:
  - создается после успешной AI processing, если появились suggested AI fields.
- `EXCHANGE_OPENED`:
  - создается, когда контрагент открывает external portal link.
- `EXCHANGE_COMMENTED`:
  - создается, когда контрагент оставляет комментарий через portal.
- `EXCHANGE_ACCEPTED`:
  - создается, когда контрагент принимает документ.
- `EXCHANGE_REJECTED`:
  - создается, когда контрагент отклоняет документ.

## Миграции

Добавлена миграция:

- `dms/migrations/0035_notifications.py`

## Проверки

Выполнено:

```powershell
.\.venv\Scripts\python.exe manage.py test dms.test_notifications --verbosity 2
.\.venv\Scripts\python.exe manage.py test dms.test_workflow_engine_mvp dms.test_ai_processing_pipeline dms.test_counterparty_portal_mvp dms.test_b2b_communication_layer --verbosity 1
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
git diff --check
```

Результат:

- Stage 24 targeted tests — 5 OK.
- Related workflow/AI/B2B tests — 15 OK.
- `manage.py check` — OK.
- `makemigrations --check --dry-run` — no changes detected.
- `migrate` — applied `dms.0035_notifications`.
- `migrate --check` — OK.
- Full `dms` suite — 117 tests OK.
- `git diff --check` — OK, only expected CRLF warnings on Windows.

## Ручная проверка

1. Login as an internal user.
2. Start workflow with an approver and verify the approver sees an unread notification.
3. Run AI processing for a document and verify the uploader/creator sees an AI review notification.
4. Create outgoing exchange, open/comment/accept/reject from the external portal, then verify internal notifications.
5. Open `/notifications/` and verify only the current user's notifications are listed.
6. Mark a notification as read and verify the unread counter decreases.
7. Verify notification messages do not contain secure portal tokens or portal token URLs.
8. Verify users from another organization cannot see or mark these notifications.

## Ограничения

- No email delivery was added.
- No external push service was added.
- No external counterparty accounts were added.
- No secure portal token is stored in notification title/message.
- Stage 25 was not started.
