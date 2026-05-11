# Stage 33 — Production Pilot / Пилотное внедрение

## Цель этапа

Подготовить проект к реальному пилотному внедрению у клиента.

Этот этап должен собрать стабильную pilot-ready конфигурацию.

## Что подготовить

- pilot deployment checklist;
- pilot environment settings;
- demo/pilot seed;
- backup checklist;
- restore checklist;
- admin onboarding;
- user onboarding;
- pilot QA сценарий;
- known limitations;
- rollback plan.

## Кодовые изменения

Кодовые изменения должны быть минимальными.

Можно добавлять:

- management commands для pilot checks;
- документацию;
- health checks;
- small fixes для deployment/pilot readiness.

Нельзя добавлять новые крупные product features.

## Пилотная среда

Документация должна требовать:

- DEBUG=False;
- strong secret key;
- real allowed hosts;
- CSRF trusted origins;
- HTTPS через reverse proxy;
- secure cookies;
- backups;
- health check;
- no committed secrets.

## Чего нельзя делать

- Не использовать реальные данные клиента без соглашения.
- Не запускать пилот без backup.
- Не обещать функции, которых нет.
- Не начинать Stage 34.

## Тесты

Добавить tests только если есть кодовые изменения.

Обязательно проверить существующий full suite.

## Проверки

Выполнить:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
docker compose --env-file .env.example config --quiet
git diff --check
git status