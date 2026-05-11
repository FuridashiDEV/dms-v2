# Stage 29 — 1C-light Integration / Лёгкая интеграция с 1С

## Цель этапа

Добавить минимальную основу интеграции с 1С без попытки покрыть все конфигурации 1С.

Это должен быть безопасный MVP-сценарий:

- импорт файла/данных из 1С;
- создание обычного Document;
- связь с внешним идентификатором;
- экспорт подтверждённых данных обратно.

## Что добавить

Использовать существующий Integration Layer:

- IntegrationProvider;
- IntegrationConnection;
- IntegrationSyncJob;
- ExternalReference.

Добавить provider для 1С, если его ещё нет.

## Import flow

Система должна уметь принять файл/JSON/CSV/XML-like payload из 1С-light сценария и создать обычный Document.

## Export flow

Экспортировать только подтверждённые человеком данные.

Запрещено экспортировать неподтверждённые AI suggestions.

## Внешняя ссылка

Каждый импортированный документ должен иметь ExternalReference:

- provider = 1C;
- external_id;
- object_type;
- metadata без секретов.

## Чего нельзя делать

- Не делать полную интеграцию со всеми конфигурациями 1С.
- Не подключать тяжёлые SDK.
- Не хранить credentials в plaintext.
- Не экспортировать неподтверждённые ИИ-данные.
- Не начинать Stage 30.

## Тесты

Добавить tests:

1. 1C provider exists.
2. Import creates Document.
3. ExternalReference is created.
4. Duplicate external_id does not create duplicate document.
5. Export includes confirmed fields only.
6. Plaintext credentials are rejected.

## Проверки

Выполнить:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
git diff --check
git status