# Stage 31 - Billing 2.0 / Коммерческая модель

Дата: 2026-05-17
Ветка: `stage-31-billing-commercial-model`
Статус: completed

## Прочитанный stage-файл

- `docs/codex/31_BILLING_2.md`

## Что реализовано

- Добавлен экран коммерческой подписки организации: `/billing/`.
- Добавлен экран usage vs limits: `/billing/usage/`.
- Использованы существующие модели:
  - `Plan`;
  - `PlanQuota`;
  - `Subscription`;
  - `UsageEvent`;
  - `AuditEvent`.
- Расширен billing service:
  - `get_billing_overview`;
  - `get_usage_vs_limits` с soft warning state;
  - `get_subscription_history`;
  - `change_subscription_plan`.
- Добавлены soft warnings по лимитам:
  - `ok`;
  - `warning` при достижении 80%;
  - `exceeded` при превышении лимита;
  - `unlimited` для неограниченных квот.
- Soft warning только информирует пользователя и не блокирует product flow.
- Superuser может вручную менять plan/status подписки организации.
- История изменений подписки пишется через `AuditEvent`:
  - `billing.subscription_created`;
  - `BILLING_SUBSCRIPTION_CHANGED`.
- Подготовлены явные foundation-флаги для будущей оплаты:
  - `payment_gateway_enabled = False`;
  - `invoices_enabled = False`;
  - `hard_enforcement = False`.
- В навигацию добавлена ссылка Billing для superuser и ADMIN.
- Добавлены focused tests для Stage 31.

## Как работает коммерческая модель

1. Organization admin открывает `/billing/` и видит текущий тариф, статус подписки, лимиты, usage за месяц, предупреждения и историю.
2. Organization admin может открыть `/billing/usage/` и увидеть полный отчет usage vs limits.
3. Superuser на `/billing/` выбирает organization и может вручную изменить plan/status подписки.
4. При ручном изменении подписки сохраняется `AuditEvent` с предыдущим и новым планом/status.
5. Превышение лимитов отображается как soft warning и не блокирует создание документов, импорт, AI, workflow, exchange или другие flows.

## Ограничения этапа

- Payment gateway не подключался.
- Stripe/Kaspi/CloudPayments не добавлялись.
- Реальные invoices не создавались.
- Money movement отсутствует.
- Hard blocking по лимитам отсутствует.
- Stage 32 не начинался.

## Измененные файлы

- `dms/services/billing.py`
- `dms/views.py`
- `dms/urls.py`
- `templates/base.html`
- `templates/dms/billing_dashboard.html`
- `templates/dms/billing_usage_limits.html`
- `dms/test_billing_commercial_model_stage31.py`
- `docs/codex/progress/STAGE_31_PROGRESS.md`

## Миграции

Новых миграций нет. Stage 31 развивает существующие billing/usage модели без изменения схемы БД.

## Проверки

Выполнено:

```powershell
.\.venv\Scripts\python.exe manage.py test dms.test_billing_commercial_model_stage31 --verbosity 2
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
git diff --check
git status --short --branch
```

Результаты:

- Stage 31 focused tests: 7 OK.
- `manage.py check`: OK.
- `makemigrations --check --dry-run`: no changes detected.
- `migrate --check`: OK.
- Full `dms` suite: 156 tests OK.
- `git diff --check`: OK, только ожидаемые CRLF warnings на Windows.
- Full suite emitted existing warnings for unavailable local Qdrant, unauthenticated HuggingFace access, expected 403/404 negative permission checks, and mocked webhook transport; tests passed.

## Что нужно проверить вручную

1. Зайти superuser в `/billing/`.
2. Выбрать organization и проверить текущий тариф/status.
3. Изменить plan/status вручную и убедиться, что изменения сохранились.
4. Проверить, что в истории появилась запись об изменении подписки.
5. Зайти organization admin в `/billing/` и убедиться, что видна только своя organization.
6. Открыть `/billing/usage/` и проверить usage vs limits.
7. Проверить soft warning при превышении лимитов.
8. Убедиться, что превышение лимита не блокирует обычные product flows.
9. Убедиться, что employee получает отказ доступа к billing screens.
10. Убедиться, что UI не показывает платежные операции, реальные invoices или платежный gateway.

## Незавершенные задачи

Нет в рамках Stage 31.

Future billing tasks остаются для следующих этапов: реальные платежи, invoices, hard enforcement, customer billing portal и external payment integrations.
