# Stage 32 — Enterprise Security 2.0 / Корпоративная безопасность 2.0

## Цель этапа

Усилить безопасность проекта для корпоративных клиентов.

Это этап улучшения security controls, а не этап сертификации.

## Что добавить

Рассмотреть и реализовать безопасный минимум:

- расширенные session settings;
- audit export;
- security events dashboard;
- optional IP allowlist для организации;
- antivirus scanner integration hook improvement;
- production settings validation command;
- password/session policy settings, если совместимо с текущей auth model.

## Важно

Не ломать текущий login flow.

Не добавлять SSO/SAML/OIDC без отдельного решения, если это слишком большой объём.

Если SSO добавляется, только как foundation и только без нарушения обычного входа.

## Чего нельзя делать

- Не заявлять SOC2/ISO certification.
- Не подключать платные security services.
- Не ломать обычную авторизацию.
- Не переписывать auth полностью.
- Не начинать Stage 33.

## Тесты

Добавить tests:

1. Security settings validation does not expose secrets.
2. Audit export is access controlled.
3. IP allowlist denies unauthorized IP if enabled.
4. Normal login still works.
5. File upload security still works.
6. Portal token security still works.

## Проверки

Выполнить:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
git diff --check
git status