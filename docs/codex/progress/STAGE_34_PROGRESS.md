# Stage 34 - Enterprise Search Quality Validation

Дата: 2026-05-17
Ветка: `stage-34-enterprise-search-quality-validation`
Статус: completed

## Прочитанный stage-файл

- `docs/codex/34_ENTERPRISE_SEARCH_QUALITY_VALIDATION.md`

## Что было реализовано

- Добавлен read-only enterprise search evaluation framework: `dms.services.search_quality`.
- Добавлен synthetic golden dataset: `docs/search_quality_golden.json`.
- Добавлена management command:

```powershell
.\.venv\Scripts\python.exe manage.py evaluate_enterprise_search_quality --user <username> --dataset docs/search_quality_golden.json
```

- Добавлена поддержка записи JSON-отчета:

```powershell
.\.venv\Scripts\python.exe manage.py evaluate_enterprise_search_quality --user <username> --write-report reports/search-quality/current.json
```

- Добавлена regression comparison:

```powershell
.\.venv\Scripts\python.exe manage.py evaluate_enterprise_search_quality --user <username> --baseline reports/search-quality/baseline.json --fail-on-regression
```

- Добавлены focused tests для dataset loading, metrics, regression detection, command report writing и organization-scoped evaluation.

## Метрики

Framework считает:

- top-1 accuracy;
- top-3 accuracy;
- top-5 accuracy;
- precision@1 / precision@3 / precision@5;
- recall@1 / recall@3 / recall@5 по expected labels;
- MRR;
- entity match score;
- explanation coverage;
- negative hit count.

## Golden scenarios

`docs/search_quality_golden.json` содержит synthetic scenarios без реальных клиентских документов:

- contract/tools/3 mln/counterparty scenario;
- invision alias invoice scenario;
- workflow services act scenario.

Для реального пилота этот файл нужно расширить согласованными non-sensitive или customer-approved scenarios.

## Как не сломан Stage 25-26 search core

- Embedding model не менялась.
- Qdrant collection не менялась.
- Indexing/chunking не менялись.
- `document_list` и UI search flow не менялись.
- `score_document_for_query`, entity extraction, aliases и explanation используются как есть.
- Evaluation работает только поверх `get_allowed_documents(user)`, поэтому сохраняет organization isolation и DocumentAccess.
- Новых моделей/таблиц нет.

## Измененные файлы

- `dms/services/search_quality.py`
- `dms/management/commands/evaluate_enterprise_search_quality.py`
- `dms/test_enterprise_search_quality_stage34.py`
- `docs/search_quality_golden.json`
- `docs/codex/progress/STAGE_34_PROGRESS.md`

## Миграции

Новых миграций нет. Stage 34 не меняет схему БД.

## Проверки

Выполнено:

```powershell
.\.venv\Scripts\python.exe manage.py test dms.test_enterprise_search_quality_stage34 --verbosity 2
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py evaluate_enterprise_search_quality --user demo_admin --dataset docs/search_quality_golden.json
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
git diff --check
git status --short --branch
```

Результаты:

- Stage 34 focused tests: 5 OK.
- `manage.py check`: OK.
- `makemigrations --check --dry-run`: no changes detected.
- `migrate --check`: OK.
- `evaluate_enterprise_search_quality --user demo_admin`: command executed successfully.
- Full `dms` suite: 171 tests OK.
- `git diff --check`: OK.
- Full suite emitted existing warnings for unavailable local Qdrant, unauthenticated HuggingFace access, expected 403/404 negative permission checks, mocked webhook transport, and expected test DATABASES override warnings; tests passed.

## Комментарий по локальному запуску команды

Команда на локальном `demo_admin` выполнилась, но synthetic golden dataset не совпадает с текущими demo-документами, поэтому локальные production-like метрики были низкими. Это не ошибка framework. Для meaningful baseline нужно либо загрузить документы, соответствующие golden scenarios, либо заменить dataset на согласованный pilot/customer-approved golden set.

## Что нужно проверить вручную

1. Подготовить реальный pilot golden dataset без sensitive/client data или с явным approval.
2. Убедиться, что expected labels совпадают с реальными document titles/entities.
3. Запустить `evaluate_enterprise_search_quality` под пользователем с нужными organization permissions.
4. Сохранить первый accepted report как baseline.
5. Включить `--baseline` и `--fail-on-regression` в release/pilot QA процесс.
6. Проверить низкие top-k/MRR cases вручную на реальных документах.
7. Отдельно проверить semantic/vector behavior при доступном Qdrant, так как Stage 34 framework не меняет Qdrant и не обещает 100% точность.

## Незавершенные задачи

Нет в рамках Stage 34.

Для Stage 35 и далее остаются возможные улучшения extraction/reranking/search quality, но Stage 34 не начинал Stage 35 и не менял search core.
