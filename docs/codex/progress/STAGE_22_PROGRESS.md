# Stage 22 — Демонстрационные данные

Дата: 2026-05-12
Ветка: `stage-22-demo-data`
Статус: completed

## Цель

Подготовить идемпотентную management command `prepare_demo_data`, которая наполняет текущую DMS реалистичными синтетическими данными для демонстрации пилотного сценария.

## Что реализовано

- Команда `prepare_demo_data` пересоздает только demo-scope organization `demo-university`.
- Команда не удаляет и не изменяет данные других организаций.
- Demo seed использует только синтетические файлы, пользователей, email-адреса `example.test` и контрагентов.
- Добавлен флаг `--skip-vectors`, чтобы локально можно было быстро подготовить данные без Qdrant/embedding backend.
- Добавлен regression test на идемпотентность и сохранность недемо-данных.

## Demo credentials

Все пользователи создаются с паролем:

```text
DemoArchive2026!
```

Пользователи:

- `demo_admin` — администратор демо-организации.
- `demo_legal` — сотрудник Legal Department.
- `demo_finance` — сотрудник Finance Department.
- `demo_academic` — сотрудник Academic Office.
- `demo_archive` — сотрудник Central Archive.
- `demo_approver` — сотрудник Executive Office.

## Какие данные создаются

- Organization: `Demo University Archive` (`demo-university`).
- 5 departments: Executive Office, Legal Department, Finance Department, Academic Office, Central Archive.
- 9 folders для приказов, договоров, OCR-проекта, бюджета, академических регламентов и архива.
- 8 document types: Order, Policy, Contract, Appendix, Invoice, Completion Act, Budget, File Plan.
- 9 обычных `Document` с синтетическими PDF/TXT/CSV файлами.
- 10 `DocumentVersion`: у одного документа есть версия #2.
- 6 `DocumentRelation` для связанных документов.
- 1 `ProcessingJob` и 4 `ExtractedField` для AI review.
- 2 `WorkflowInstance`: один активный workflow и один завершенный approval workflow.
- 1 synthetic counterparty, 1 contact, 2 `DocumentExchange`, 5 exchange events и 2 messages.
- 1 `ImportBatch` и 3 `ImportFile`, включая duplicate example.
- `DocumentActivity`, `AuditEvent`, `UsageEvent`.
- Trial subscription создается автоматически, если в системе уже есть активный `Plan`.

## Как использовать для показа

```powershell
.\.venv\Scripts\python.exe manage.py prepare_demo_data --skip-vectors
```

Затем:

1. Войти как `demo_admin`.
2. Открыть Documents.
3. Найти `Contract for OCR and AI Search Pilot`.
4. Показать document detail, versions, related documents, AI suggestions, workflow, exchange history, evidence export, usage и analytics.
5. Для внешнего портала использовать путь, который команда выводит в конце: `/portal/exchanges/<demo-token>/`.

Если нужен semantic-search demo и локально доступен embedding/Qdrant backend:

```powershell
.\.venv\Scripts\python.exe manage.py prepare_demo_data
```

## Проверки

Выполнено:

```powershell
.\.venv\Scripts\python.exe manage.py prepare_demo_data --skip-vectors
.\.venv\Scripts\python.exe manage.py prepare_demo_data --skip-vectors
.\.venv\Scripts\python.exe manage.py shell -c "<demo counts smoke check>"
.\.venv\Scripts\python.exe manage.py test dms.test_demo_data_command --verbosity 2
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
```

Результат:

- `manage.py check` — OK.
- `makemigrations --check --dry-run` — no changes detected.
- `migrate --check` — OK.
- `dms.test_demo_data_command` — 1 test OK.
- `dms` test suite — 108 tests OK.

## Ручная проверка

- Проверить login для `demo_admin`, `demo_legal`, `demo_finance`.
- Проверить document list и detail для demo documents.
- Проверить, что `demo_legal` видит legal documents и связанные demo flows.
- Проверить AI review страницу для `Contract for OCR and AI Search Pilot`.
- Проверить workflow block на document detail.
- Проверить related documents block.
- Проверить exchange list/history и external portal по token URL из вывода команды.
- Проверить evidence export.
- Проверить usage/analytics dashboard.
- Проверить повторный запуск команды: demo data должна пересоздаваться без дублей.

## Риски и ограничения

- Внешний portal token является демонстрационным и пересоздается при каждом запуске seed-команды.
- Semantic vectors не создаются при `--skip-vectors`; для semantic-search демо нужен доступный embedding/Qdrant backend.
- Данные предназначены только для демо и не должны смешиваться с production/customer data.

## Следующий этап

Stage 23 не начинался.
