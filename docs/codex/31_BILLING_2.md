# Stage 31 — Billing 2.0 / Коммерческая модель

## Цель этапа

Развить текущую тарифную основу до понятной коммерческой модели без подключения реальных платежей.

## Текущий контекст

В проекте уже есть:

- Plan;
- PlanQuota;
- Subscription;
- UsageEvent;
- monthly usage aggregation;
- usage-vs-limit reporting.

## Что добавить

- экран просмотра подписки организации;
- экран usage vs limits;
- soft warning при превышении лимита;
- trial status, если нужно;
- ручное изменение тарифа администратором;
- историю изменений подписки;
- подготовку к будущей оплате.

## Важно

На этом этапе не подключать payment gateway.

Не создавать реальные invoices.

Не блокировать пользователей жёстко, если это не указано отдельно.

## Как должно работать

Администратор организации видит:

- текущий тариф;
- лимиты;
- использование за месяц;
- превышения;
- предупреждения.

Superuser может менять план организации вручную.

## Чего нельзя делать

- Не подключать Stripe/Kaspi/CloudPayments.
- Не создавать реальные счета.
- Не выполнять money movement.
- Не блокировать пользователя внезапно.
- Не начинать Stage 32.

## Тесты

Добавить tests:

1. Organization admin sees own subscription.
2. Other organization cannot see subscription.
3. Superuser can change plan.
4. Usage report shows exceeded limits.
5. Soft warning does not block product flow.
6. No payment logic exists.

## Проверки

Выполнить:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
git diff --check
git status