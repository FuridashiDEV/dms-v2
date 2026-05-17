# Stage 28 — Email Ingestion / Приём документов из почты

Дата: 2026-05-17
Ветка: `stage-28-email-ingestion`
Статус: completed

## Прочитанный stage-файл

- `docs/codex/28_EMAIL_INGESTION.md`

## Что реализовано

- Добавлен service-layer `dms.services.email_ingestion` для минимального email ingestion без полноценного почтового клиента.
- Добавлен парсинг одного `.eml` сообщения через стандартную библиотеку Python.
- Добавлено извлечение вложений из письма.
- Каждое вложение проходит текущую upload validation через `validate_uploaded_file`.
- Валидное вложение создаётся как обычный `Document` через существующий `create_document_from_uploaded_file`.
- Для каждого созданного документа автоматически создаётся `DocumentVersion` существующим document creation flow.
- Связь письма и документа сохраняется через существующую модель `ExternalReference`.
- Metadata письма сохраняет:
  - `message_id`;
  - `sender`;
  - `subject`;
  - `received_at`;
  - `attachment_file_name`;
  - `attachment_content_type`;
  - `attachment_sha256`;
  - `mailbox`, если он задан в безопасных настройках connection.
- Повторная обработка того же письма с тем же вложением не создаёт дубликат документа: idempotency работает через deterministic `external_id` по `message_id + file_name + attachment_sha256`.
- Добавлена management command `ingest_email_message` для обработки одного локального `.eml` файла.
- Добавлены focused tests для Stage 28.

## Как работает приём документов из почты

1. Администратор или operator создаёт/использует `IntegrationConnection` с email provider.
2. Секреты почтового ящика не кладутся в JSON; допускается только безопасная ссылка в `secret_ref`, например `env:EMAIL_INGESTION_PASSWORD` или vault reference.
3. Команда получает локальный `.eml` файл:

```powershell
.\.venv\Scripts\python.exe manage.py ingest_email_message --connection-id <id> --department-id <id> --user-id <id> --file C:\path\message.eml
```

4. Сервис извлекает вложения.
5. Для каждого вложения:
   - проверяет файл текущей upload validation;
   - проверяет, не был ли attachment уже обработан;
   - создаёт обычный `Document`;
   - создаёт `DocumentVersion`;
   - создаёт `ExternalReference` с email metadata;
   - обновляет `IntegrationSyncJob`.

## Изменённые файлы

- `dms/services/email_ingestion.py`
- `dms/management/commands/ingest_email_message.py`
- `dms/test_email_ingestion_stage28.py`
- `docs/codex/progress/STAGE_28_PROGRESS.md`

## Миграции

Новых миграций нет. Stage 28 использует существующие модели:

- `IntegrationProvider`
- `IntegrationConnection`
- `IntegrationSyncJob`
- `ExternalReference`
- `Document`
- `DocumentVersion`

## Проверки

Выполнено:

```powershell
.\.venv\Scripts\python.exe manage.py test dms.test_email_ingestion_stage28 --verbosity 2
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
git diff --cached --check
git status --short --branch
```

Результаты:

- Stage 28 focused tests: 5 OK.
- `manage.py check`: OK.
- `makemigrations --check --dry-run`: no changes detected.
- `migrate --check`: OK.
- Full `dms` suite: 137 tests OK.
- `git diff --cached --check`: OK, only expected CRLF warnings on Windows.
- `git status --short --branch`: Stage 28 files staged; unrelated pre-existing `docs/codex` deletions/untracked stage files remain unstaged.
- Full suite emitted existing warnings for unavailable local Qdrant and unauthenticated HuggingFace access; tests passed.

## Что нужно проверить вручную

1. Создать email `IntegrationConnection` с `secret_ref`, без пароля в JSON.
2. Подготовить `.eml` письмо с безопасным вложением `.txt`, `.pdf` или `.docx`.
3. Запустить `ingest_email_message` с нужным `connection-id`, `department-id`, `user-id`.
4. Открыть созданный документ в DMS и проверить:
   - документ виден как обычный `Document`;
   - `DocumentVersion #1` создана;
   - `source_system = email_ingestion`;
   - `ExternalReference` содержит metadata письма.
5. Повторно запустить ту же команду на том же `.eml` и проверить, что новый документ не создаётся.
6. Проверить `.eml` с запрещённым вложением `.exe`: документ не должен создаваться.
7. Проверить, что connection одной organization нельзя использовать для department другой organization.

## Ограничения

- Полноценный IMAP/SMTP почтовый клиент не добавлялся.
- Автоматическое расписание получения писем не добавлялось.
- Письма из ящика не удаляются и не помечаются автоматически.
- AI processing для email ingestion по умолчанию выключен, чтобы не запускать тяжёлую обработку массово.
- Сырые тела писем и полные headers не сохраняются.
- Пароли, access tokens и другие секреты не сохраняются в открытом JSON.
- Stage 29 не начинался.
