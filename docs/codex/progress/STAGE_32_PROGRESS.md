# Stage 32 - Enterprise Security 2.0 / Корпоративная безопасность 2.0

Дата: 2026-05-17
Ветка: `stage-32-enterprise-security-2`
Статус: completed

## Прочитанный stage-файл

- `docs/codex/32_ENTERPRISE_SECURITY_2.md`

## Что реализовано

- Добавлен security service `dms.services.enterprise_security`.
- Добавлен security dashboard: `/security/`.
- Добавлен access-controlled audit CSV export: `/security/audit-export/`.
- Добавлен optional organization IP allowlist через `DMS_ORGANIZATION_IP_ALLOWLISTS`.
- Добавлен middleware `OrganizationIPAllowlistMiddleware`.
- Добавлена команда production settings validation:

```powershell
.\.venv\Scripts\python.exe manage.py validate_production_security
```

- Добавлены security audit events:
  - `SECURITY_LOGIN_SUCCESS`;
  - `SECURITY_LOGIN_FAILURE`;
  - `SECURITY_LOGIN_RATE_LIMITED`;
  - `SECURITY_IP_ALLOWLIST_DENIED`;
  - `SECURITY_AUDIT_EXPORTED`.
- Audit export redacts sensitive metadata keys:
  - token;
  - secret;
  - password;
  - api_key / apikey;
  - private_key;
  - access_key;
  - authorization;
  - cookie;
  - session.
- Улучшен antivirus scanner hook:
  - `DMS_ANTIVIRUS_SCANNER` остается optional;
  - `DMS_ANTIVIRUS_FAIL_CLOSED=True` позволяет отклонять upload, если scanner hook недоступен.
- Обновлен `docs/SECURITY_BASELINE.md`.
- Добавлены focused tests для Stage 32.

## Security controls

1. Security dashboard доступен только superuser и organization ADMIN.
2. Organization ADMIN видит только события своей organization.
3. Superuser может выбирать organization на security dashboard.
4. Audit CSV export scope ограничен organization-доступом пользователя.
5. Sensitive metadata не попадает в audit export в открытом виде.
6. Optional IP allowlist блокирует authenticated internal routes при несовпадении IP.
7. Login/logout/health/external portal routes не блокируются IP allowlist, чтобы обычный вход и secure portal продолжали работать.
8. Login success/failure/rate limit пишутся в audit trail.
9. Production validation command проверяет secure settings без вывода secrets.
10. File upload validation и portal token flow сохранены.

## Ограничения

- Auth system не переписывался.
- SSO/SAML/OIDC не добавлялись.
- Платные security services не подключались.
- SOC2/ISO или другие certification claims не заявлялись.
- Реальный antivirus engine не добавлялся; оставлен hook.
- Stage 33 не начинался.

## Измененные файлы

- `.env.example`
- `config/settings.py`
- `dms/middleware.py`
- `dms/services/enterprise_security.py`
- `dms/services/security.py`
- `dms/management/commands/validate_production_security.py`
- `dms/views.py`
- `dms/urls.py`
- `templates/base.html`
- `templates/dms/security_dashboard.html`
- `dms/test_enterprise_security_stage32.py`
- `docs/SECURITY_BASELINE.md`
- `docs/codex/progress/STAGE_32_PROGRESS.md`

## Миграции

Новых миграций нет. Stage 32 не меняет схему БД.

## Проверки

Выполнено:

```powershell
.\.venv\Scripts\python.exe manage.py test dms.test_enterprise_security_stage32 --verbosity 2
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
.\.venv\Scripts\python.exe manage.py validate_production_security
git diff --check
git status --short --branch
```

Результаты:

- Stage 32 focused tests: 7 OK.
- `manage.py check`: OK.
- `makemigrations --check --dry-run`: no changes detected.
- `migrate --check`: OK.
- Full `dms` suite: 163 tests OK.
- `validate_production_security`: passed with production-like env overrides.
- `git diff --check`: OK, только ожидаемые CRLF warnings на Windows.
- Full suite emitted existing warnings for unavailable local Qdrant, unauthenticated HuggingFace access, expected 403/404 negative permission checks, and mocked webhook transport; tests passed.

## Что нужно проверить вручную

1. Superuser открывает `/security/`, выбирает organization и видит security metrics.
2. Organization ADMIN открывает `/security/` и видит только свою organization.
3. Employee получает отказ доступа к `/security/` и `/security/audit-export/`.
4. Выполнить audit export и проверить CSV без raw token/secret/password/API key.
5. Настроить `DMS_ORGANIZATION_IP_ALLOWLISTS` для тестовой organization и проверить allowed/denied IP.
6. Проверить, что `/login/` работает при включенном IP allowlist.
7. Проверить, что внешний portal token flow продолжает открываться без login.
8. Проверить upload разрешенных файлов и блокировку опасных MIME/extensions.
9. Проверить `DMS_ANTIVIRUS_FAIL_CLOSED=True` в окружении с реальным scanner hook перед включением в production.
10. Запустить `validate_production_security` в production-like env и устранить warnings/errors перед релизом.

## Незавершенные задачи

Нет в рамках Stage 32.

Дальнейшие security capabilities остаются для будущих этапов: SSO/SAML/OIDC, реальный antivirus/EDR integration, SIEM forwarding, DLP, formal compliance automation и security certification work.
