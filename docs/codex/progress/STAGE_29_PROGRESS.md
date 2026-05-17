# Stage 29 — 1C-light Integration / Лёгкая интеграция с 1С

Дата: 2026-05-17
Ветка: `stage-29-1c-light-integration`
Статус: completed

## Прочитанный stage-файл

- `docs/codex/29_1C_LIGHT_INTEGRATION.md`

## Что реализовано

- Добавлен service-layer `dms.services.one_c_light` поверх существующего Integration Layer.
- Используются существующие модели:
  - `IntegrationProvider`;
  - `IntegrationConnection`;
  - `IntegrationSyncJob`;
  - `ExternalReference`;
  - `Document`;
  - `DocumentVersion`;
  - `ExtractedField`.
- Provider `1c` уже существует и seeded через Integration Layer; новая модель provider не добавлялась.
- Добавлен import flow для одного файла/payload из 1C-light сценария.
- Импорт создаёт обычный `Document` через существующий `create_document_from_uploaded_file`.
- Для импортированного документа создаётся `DocumentVersion #1`.
- Создаётся `ExternalReference` с provider `1c`, `external_id`, `object_type` и metadata без секретов.
- Duplicate detection работает по `(connection, external_id)` через существующий уникальный контракт `ExternalReference`.
- Добавлен export flow `build_1c_light_export_payload`, который возвращает только human-confirmed/applied поля:
  - `ExtractedField.Status.CONFIRMED`;
  - `ExtractedField.Status.APPLIED`.
- `ExtractedField.Status.SUGGESTED` и rejected AI suggestions в export не попадают.
- Добавлены management commands:
  - `import_1c_light`;
  - `export_1c_light`.
- Добавлены focused tests для Stage 29.

## Что поддерживает 1C-light сценарий

Поддерживается безопасный MVP, а не полная интеграция со всеми конфигурациями 1С:

1. Импорт одного локального файла или payload:
   - JSON;
   - CSV;
   - XML-like файл;
   - обычный документный файл, если он проходит текущую upload validation.
2. Создание обычного `Document` в выбранном department.
3. Создание `DocumentVersion`.
4. Связь документа с внешним объектом 1С через `ExternalReference`.
5. Idempotency по `external_id`: повторный импорт того же внешнего ID не создаёт новый документ.
6. Export payload для передачи обратно во внешнюю систему:
   - document metadata;
   - external reference;
   - только confirmed/applied extracted fields.

Пример импорта:

```powershell
.\.venv\Scripts\python.exe manage.py import_1c_light --connection-id <id> --department-id <id> --user-id <id> --external-id <1c-guid-or-ref> --object-type invoice --file C:\path\payload.json
```

Пример export:

```powershell
.\.venv\Scripts\python.exe manage.py export_1c_light --document-id <id> --connection-id <id>
```

## Безопасность и ограничения

- Тяжёлые 1C SDK не подключались.
- Полный почтовый/HTTP/OData/SOAP-клиент для 1С не добавлялся.
- Полная поддержка всех конфигураций 1С не добавлялась.
- Credentials не сохраняются в plaintext JSON; используется существующий `secret_ref`.
- Metadata проходит существующую проверку `validate_no_plaintext_secrets`.
- Organization isolation проверяется на import и export.
- Export не включает неподтверждённые AI suggestions.
- Stage 30 не начинался.

## Изменённые файлы

- `dms/services/one_c_light.py`
- `dms/management/commands/import_1c_light.py`
- `dms/management/commands/export_1c_light.py`
- `dms/test_one_c_light_integration.py`
- `docs/codex/progress/STAGE_29_PROGRESS.md`

## Миграции

Новых миграций нет.

## Проверки

Выполнено:

```powershell
.\.venv\Scripts\python.exe manage.py test dms.test_one_c_light_integration --verbosity 2
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
git diff --check
git status --short --branch
```

Результаты:

- Stage 29 focused tests: 6 OK.
- `manage.py check`: OK.
- `makemigrations --check --dry-run`: no changes detected.
- `migrate --check`: OK.
- Full `dms` suite: 143 tests OK.
- `git diff --check`: OK.
- `git status --short --branch`: Stage 29 files present; unrelated pre-existing `docs/codex` deletions/untracked stage files remain unstaged.
- Full suite emitted existing warnings for unavailable local Qdrant and unauthenticated HuggingFace access; tests passed.

## Что нужно проверить вручную

1. Создать или использовать `IntegrationConnection` для provider `1c` с безопасным `secret_ref`.
2. Подготовить JSON/CSV/XML-like payload из 1С-light сценария.
3. Запустить `import_1c_light` с `external-id` и `object-type`.
4. Открыть созданный документ и проверить:
   - документ обычный `Document`;
   - создана `DocumentVersion #1`;
   - `source_system = 1c_light`;
   - `ExternalReference` содержит provider `1c`, external ID и object type.
5. Повторить импорт с тем же `external-id` и проверить, что duplicate не создаёт новый документ.
6. Подтвердить AI/metadata поля вручную в DMS.
7. Запустить `export_1c_light` и проверить, что в JSON export есть только confirmed/applied fields.
8. Проверить, что suggested/rejected AI fields не попадают в export.
