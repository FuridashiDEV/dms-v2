# Stage 33 - Production Pilot / Пилотное внедрение

Дата: 2026-05-17
Ветка: `stage-33-production-pilot`
Статус: completed

## Прочитанный stage-файл

- `docs/codex/33_PRODUCTION_PILOT.md`

## Цель этапа

Подготовить проект к контролируемому pilot deployment без добавления крупных product features и без перехода к Stage 34.

## Что реализовано

- Добавлен pilot-specific runbook: `docs/PILOT_RUNBOOK.md`.
- Добавлена management command:

```powershell
.\.venv\Scripts\python.exe manage.py check_pilot_readiness
```

- Команда проверяет pilot/environment readiness без вывода secrets:
  - production security settings через существующий Stage 32 validation service;
  - наличие обязательных operational docs;
  - non-placeholder database password;
  - non-local-only allowed hosts warning;
  - CSRF trusted origins warning;
  - database health check warning.
- Добавлен strict mode:

```powershell
.\.venv\Scripts\python.exe manage.py check_pilot_readiness --strict
```

- Обновлен `docs/DEPLOYMENT.md` с pilot readiness checks.
- Обновлен `docs/QA_CHECKLIST.md` с pilot backup/restore/onboarding checks.
- Обновлен `docs/README.md` с ссылкой на pilot runbook и актуальными route entries.
- Добавлены focused tests для Stage 33 command.

## Что готово для пилота

- Pilot go/no-go checklist.
- Pilot environment safety requirements:
  - `DEBUG=False`;
  - strong `DJANGO_SECRET_KEY`;
  - real `DJANGO_ALLOWED_HOSTS`;
  - real `DJANGO_CSRF_TRUSTED_ORIGINS`;
  - HTTPS/reverse proxy;
  - secure cookies;
  - no committed secrets.
- Demo/pilot seed guidance через `prepare_demo_data`.
- Backup checklist.
- Restore checklist.
- Admin onboarding checklist.
- User onboarding checklist.
- Pilot QA scenario.
- Known limitations.
- Rollback plan.
- Health check expectations for `/health/`.
- Pilot readiness command.

## Ограничения

- Новые крупные product features не добавлялись.
- Реальные клиентские данные не использовались.
- Платные сервисы, SSO, e-signature, billing/payment integrations и Stage 34 не начинались.
- Backup/restore описаны и должны быть проверены на реальных pilot volumes вручную.

## Измененные файлы

- `dms/management/commands/check_pilot_readiness.py`
- `dms/test_production_pilot_stage33.py`
- `docs/PILOT_RUNBOOK.md`
- `docs/DEPLOYMENT.md`
- `docs/QA_CHECKLIST.md`
- `docs/README.md`
- `docs/codex/progress/STAGE_33_PROGRESS.md`

## Миграции

Новых миграций нет. Stage 33 не меняет схему БД.

## Проверки

Выполнено:

```powershell
.\.venv\Scripts\python.exe manage.py test dms.test_production_pilot_stage33 --verbosity 2
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py check_pilot_readiness
docker compose --env-file .env.example config --quiet
git diff --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
git status --short --branch
```

Результаты:

- Stage 33 focused tests: 3 OK.
- `manage.py check`: OK.
- `makemigrations --check --dry-run`: no changes detected.
- `migrate --check`: OK.
- `check_pilot_readiness`: passed with production-like env overrides.
- `docker compose --env-file .env.example config --quiet`: OK.
- `git diff --check`: OK, только ожидаемые CRLF warnings на Windows.
- Full `dms` suite: 166 tests OK.
- Full suite emitted existing warnings for unavailable local Qdrant, unauthenticated HuggingFace access, expected 403/404 negative permission checks, and mocked webhook transport; tests passed.

## Что нужно проверить вручную

1. Настроить реальный pilot `.env` без placeholder secrets.
2. Проверить HTTPS/reverse proxy и secure cookies на pilot host.
3. Открыть `/health/` снаружи pilot environment.
4. Запустить `validate_production_security` на pilot environment.
5. Запустить `check_pilot_readiness --strict` на pilot environment и принять/исправить findings.
6. Создать PostgreSQL backup.
7. Создать media backup.
8. Проверить restore на non-production target.
9. Прогнать pilot QA scenario из `docs/PILOT_RUNBOOK.md`.
10. Провести admin onboarding.
11. Провести user onboarding.
12. Проверить search/AI quality на согласованных representative documents.
13. Проверить rollback plan в тестовой среде.

## Незавершенные задачи

Нет в рамках Stage 33.

Остаются manual pilot tasks: реальные hostnames/TLS, реальные backup locations, restore rehearsal, customer-approved data loading, operational ownership и acceptance sign-off.
