# Stage 26 — Search Experience and Quality Evaluation

Дата: 2026-05-13
Ветка: `stage-26-search-experience`
Статус: completed

## Прочитанный stage-файл

- `docs/codex/26_SEARCH_EXPERIENCE_AND_QUALITY_EVALUATION.md`

## Что было реализовано

- Улучшена существующая страница поиска документов без переписывания Stage 25 search core.
- Добавлены режимы поиска: hybrid, exact, semantic.
- Hybrid остаётся режимом по умолчанию.
- Добавлены UX-фильтры по counterparty и amount range поверх существующих фильтров по типу, дате, отделу, папке и статусу.
- Добавлены найденные фрагменты текста для результатов.
- Улучшено отображение explanation и matched entities.
- В выдаче показываются связанные документы, но только если текущий пользователь имеет к ним доступ.
- Semantic mode безопасно деградирует в text/entity fallback при недоступном embedding/Qdrant.
- Добавлена команда оценки качества поиска.
- Добавлена документация `docs/SEARCH_GUIDE.md`.

## Какие search services/views/templates изменены

- `dms/forms.py`
  - расширен `DocumentSearchForm`;
  - добавлены `search_mode`, `counterparty`, `amount_min`, `amount_max`.
- `dms/services/search_experience.py`
  - добавлены UX helpers для режимов поиска, фильтров, snippets, matched entities, related documents и quality evaluation.
- `dms/views.py`
  - `document_list` теперь учитывает выбранный режим поиска;
  - exact mode не вызывает embeddings/Qdrant;
  - semantic mode использует fallback, если semantic layer недоступен;
  - результаты получают snippet, explanation, matched entities и accessible related documents.
- `templates/dms/document_list.html`
  - добавлен selector режима поиска;
  - добавлены поля counterparty/amount filters;
  - добавлено отображение degraded state, snippets, matched entities и related documents.
- `dms/management/commands/evaluate_search_quality.py`
  - добавлена команда QA-оценки.

## Какие режимы поиска доступны

- `hybrid` — default; text/entity/alias + semantic Qdrant hits.
- `exact` — text/entity/alias only, без embeddings/Qdrant.
- `semantic` — semantic-first; при недоступности semantic layer показывает safe fallback.

## Какие фильтры доступны

- search query;
- search mode;
- document type;
- counterparty;
- amount min/max;
- document date from/to;
- department;
- folder;
- status.

## Как работает explanation

Stage 25 `score_document_for_query` продолжает формировать причины совпадения. Stage 26 показывает эти причины в карточке результата и дополнительно выводит matched entities, если сущности запроса совпали с нормализованными сущностями документа.

Raw Qdrant payload в UI не выводится.

## Как показываются найденные фрагменты

`build_search_snippet` берёт description/extracted_text/title/source filename, ищет query terms и aliases, затем показывает короткий фрагмент вокруг первого совпадения. Если точного совпадения нет, показывается безопасный начальный фрагмент доступного текста.

## Как учитываются связанные документы

Для каждого результата Stage 26 смотрит `DocumentRelation` в обе стороны и показывает только те related documents, ID которых входят в `get_allowed_documents(user)`. Cross-organization и недоступные department documents не раскрываются.

## Как запустить оценку качества поиска

Быстрый запуск на доступных документах пользователя:

```powershell
.\.venv\Scripts\python.exe manage.py evaluate_search_quality --user demo_admin --limit 5
```

С JSON cases:

```powershell
.\.venv\Scripts\python.exe manage.py evaluate_search_quality --user demo_admin --cases docs/search_cases.json --limit 5
```

Формат cases:

```json
[
  {
    "query": "contract with IP Firma for tools",
    "expected_title_contains": "Contract with IP Firma"
  }
]
```

Метрика является QA-индикатором, а не математической гарантией точности.

## Проверки

Выполнено:

```powershell
.\.venv\Scripts\python.exe manage.py test dms.test_search_experience_stage26 --verbosity 2
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py evaluate_search_quality --user demo_admin --limit 5
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
git diff --check
git status
```

Результат:

- Stage 26 focused tests: 5 OK.
- `manage.py check`: OK.
- `makemigrations --check --dry-run`: no changes detected.
- `migrate --check`: OK.
- `evaluate_search_quality --user demo_admin --limit 5`: matched 5/5, precision@5=1.00 on demo data.
- Full `dms` suite: 129 tests OK.
- Full suite loaded BGE-M3 and emitted expected HuggingFace/Windows cache symlink warnings; tests still passed.

## Что нужно проверить вручную на реальных документах

1. Search page opens and keeps hybrid as default.
2. Exact mode does not depend on Qdrant and returns strict text/entity matches.
3. Semantic mode returns vector results when Qdrant is available.
4. Semantic mode falls back safely when Qdrant is unavailable.
5. Counterparty + amount filters narrow results correctly.
6. Snippets show useful fragments from real extracted text.
7. Explanation helps understand why the document was found.
8. Related documents appear only when accessible to the current user.
9. Users from another organization cannot infer documents through search, snippets or related results.
10. Run `evaluate_search_quality` with a curated real pilot cases file.

## Ограничения

- Stage 26 did not create new entity/alias models.
- Stage 26 did not change embedding model or Qdrant collection.
- Search quality evaluation is a lightweight QA tool, not a guarantee of 100% relevance.
- Stage 27 was not started.
