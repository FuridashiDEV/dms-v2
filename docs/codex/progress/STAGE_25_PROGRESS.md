# Stage 25 — Search Intelligence and Entity Extraction

Дата: 2026-05-13
Ветка: `stage-25-search-intelligence`
Статус: completed

## Прочитанный stage-файл

Запрошенный путь `docs/codex/25_SEARCH_INTELLIGENCE_AND_ENTITY_EXTRACTION.md` в рабочем дереве отсутствовал. Фактически прочитан доступный файл:

- `docs/codex/25_SEARCH_INTELLIGENCE_AND_ENTITY_EXTRACTION.md.md`

## Что показал аудит текущего поиска

- Извлечение текста уже было в `dms/services/text_extractor.py`.
- Embeddings строились в `dms/services/embedding.py`.
- Qdrant-слой был в `dms/services/vector_store.py`; также есть более старый `dms/services/qdrant_client.py`.
- Индексация документов была в `dms/services/document_indexing.py`; demo seed отдельно индексировал документы в `prepare_demo_data`.
- Основной пользовательский поиск работает через `dms/views.py::document_list` и `templates/dms/document_list.html`.
- Права доступа к документам применяются через `dms/utils.py::get_allowed_documents`.
- До Stage 25 использовалась hardcoded модель `all-MiniLM-L6-v2`.
- На один документ создавался один Qdrant point/vector.
- Payload Qdrant содержал базовые поля: title, organization_id, department_id, folder_id, doc_type_id, doc_date. Demo payload раньше не сохранял `organization_id`.
- Organization isolation и DocumentAccess финально применялись через SQL queryset, но Qdrant-фильтр был только по department и мог пропускать документы с явным `DocumentAccess`.

## Что было сломано или неэффективно

- Поиск бизнес-запросов не разбирал `document_type`, `counterparty`, `subject`, `amount`.
- Алиасы вроде `invision` / `инвижн` не были отдельным сигналом ранжирования.
- Один общий vector на документ был слишком грубым для длинных деловых документов.
- Не было правила "одна Qdrant collection = одна embedding-модель".
- Не было management command для полной/частичной переиндексации.
- При недоступном Qdrant fallback был в основном текстовым и не объяснял, почему результат найден.
- Vector payload был недостаточен для диагностики и безопасной фильтрации.

## Что исправлено

- Добавлены normalized search fields в `Document`:
  - `search_text_normalized`;
  - `search_entities`;
  - `search_embedding_model`;
  - `search_index_version`;
  - `search_indexed_at`.
- Добавлен service `dms/services/search_intelligence.py` для нормализации запроса, aliases, entity extraction, chunking и explainable scoring.
- `document_list` переведен на hybrid scoring: entities + aliases + text + vectors.
- Qdrant search теперь фильтруется по allowed organizations, а финальный результат всё равно проходит `get_allowed_documents`, включая department-based access и `DocumentAccess`.
- Индексация теперь создаёт несколько chunks/points на документ: title, metadata, entities, content chunks.
- Qdrant payload теперь содержит `document_id`, `chunk_key`, `chunk_kind`, `text_preview`, organization/department/folder/doc_type metadata, entities, embedding model и search index version.
- Demo data indexing теперь использует общий `index_document`.
- Добавлена команда `reindex_search`.
- В list UI добавлено отображение interpreted query и explain reasons для найденных документов.

## Какие модели и сервисы добавлены

- Модель `Document` расширена search metadata fields.
- Добавлен `dms/services/search_intelligence.py`.
- Обновлены:
  - `dms/services/embedding.py`;
  - `dms/services/vector_store.py`;
  - `dms/services/document_indexing.py`.
- Добавлена management command:
  - `dms/management/commands/reindex_search.py`.

## Какие сущности теперь извлекаются

- `document_type`: contract, invoice, act, order, appendix, policy.
- `counterparty`: например `ип фирма`.
- `subject`: например `поставку инструментов`.
- `amount`: value/raw/currency, например `3 млн` -> `3000000`.
- `key_phrases`: нормализованные поисковые токены.
- `aliases`: варианты написания и русифицированные формы.

## Как работают алиасы

- Алиасы задаются в `DEFAULT_ALIASES` внутри `dms/services/search_intelligence.py`.
- Поддержан пример `invision` / `инвижн` / `инвижен` / `in vision`.
- Можно расширять через `settings.SEARCH_ALIASES`.
- Алиасы добавляются в expanded query и участвуют в SQL fallback, Qdrant embedding text и explainable scoring.

## Как работает переиндексация

Команда:

```powershell
.\.venv\Scripts\python.exe manage.py reindex_search
```

Опции:

```powershell
.\.venv\Scripts\python.exe manage.py reindex_search --document-id 123
.\.venv\Scripts\python.exe manage.py reindex_search --organization-id 1
.\.venv\Scripts\python.exe manage.py reindex_search --only-stale
.\.venv\Scripts\python.exe manage.py reindex_search --limit 100
```

Команда пересобирает normalized metadata в `Document`, удаляет старые Qdrant points документа и записывает multi-level chunks в collection текущей embedding-модели.

## Embedding model и Qdrant collection

По умолчанию используется:

- `SEARCH_EMBEDDING_MODEL=BAAI/bge-m3`
- `SEARCH_EMBEDDING_VECTOR_SIZE=1024`
- Qdrant collection: `documents_baai_bge_m3`, если `QDRANT_COLLECTION` явно не задан.

Переключение на all-MiniLM fallback:

```powershell
$env:SEARCH_EMBEDDING_MODEL="all-MiniLM-L6-v2"
$env:SEARCH_EMBEDDING_VECTOR_SIZE="384"
```

Переключение на multilingual-e5-large:

```powershell
$env:SEARCH_EMBEDDING_MODEL="intfloat/multilingual-e5-large"
$env:SEARCH_EMBEDDING_VECTOR_SIZE="1024"
```

Для каждой модели автоматически формируется отдельный collection suffix, если не переопределять `QDRANT_COLLECTION`. Полноценное использование BGE-M3/e5 зависит от возможности окружения скачать и загрузить модель через `sentence-transformers`; `all-MiniLM-L6-v2` остаётся лёгким fallback.

## Миграции

Добавлена миграция:

- `dms/migrations/0036_document_search_intelligence.py`

## Тесты и проверки

Выполнено:

```powershell
.\.venv\Scripts\python.exe manage.py test dms.test_search_intelligence_stage25 dms.test_semantic_search_ranking dms.test_vector_store_resilience --verbosity 1
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py migrate dms 0036
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
git diff --check
git status
```

Результат:

- Targeted Stage 25/search tests: 10 OK.
- `manage.py check`: OK.
- `makemigrations --check --dry-run`: no changes detected.
- Initial `migrate --check`: failed because local DB had unapplied `0036_document_search_intelligence`.
- `migrate dms 0036`: OK.
- Re-run `migrate --check`: OK.
- Full `dms` suite: 124 tests OK.
- `git diff --check`: OK, only expected CRLF warnings on Windows.
- `git status`: branch has Stage 25 changes plus pre-existing untracked/deleted stage docs that were not modified or staged by this work.

## Что нужно проверить вручную на реальных документах

1. Загрузить реальный договор с контрагентом, предметом и суммой.
2. Выполнить `reindex_search` для документа или организации.
3. Проверить запрос: `договор с ИП Фирма на поставку инструментов на 3 млн`.
4. Проверить alias query: `инвижн`, `invision`, `in vision`.
5. Проверить, что employee не видит документы другой organization.
6. Проверить, что employee не видит документы чужого department без `DocumentAccess`.
7. Проверить, что документ с `DocumentAccess` виден через vector hit и через fallback.
8. Остановить Qdrant и проверить безопасную деградацию в текстовый/entity/alias поиск.
9. Проверить качество BGE-M3/e5-large только в окружении, где можно безопасно скачать модели и выполнить полную переиндексацию в отдельную collection.

## Ограничения

- Stage 25 не заявляет 100% точность извлечения сущностей.
- AI suggestions не применяются к `Document` автоматически.
- BGE-M3 теперь модель по умолчанию, но её первая загрузка зависит от доступа окружения к модели; `all-MiniLM-L6-v2` остаётся fallback через env.
- Stage 26 не начат.
