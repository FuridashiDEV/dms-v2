# Stage 27 — Evidence Package 2.0

Дата: 2026-05-17
Ветка: `stage-27-evidence-package-2`
Статус: completed

## Прочитанный stage-файл

- `docs/codex/27_EVIDENCE_PACKAGE_2.md`

## Что реализовано

- Добавлен человекочитаемый HTML evidence report поверх существующего JSON evidence service.
- Добавлен route:
  - `/documents/<id>/evidence/report/`
  - URL name: `dms:document_evidence_report`
- Добавлена кнопка `Evidence report` в карточку документа рядом с `Evidence JSON`.
- Добавлен service-layer `dms.services.evidence_report`:
  - формирует timeline;
  - считает SHA-256 checksum отчёта по sanitized evidence package;
  - передаёт ограничения отчёта в template.
- Усилена redaction-логика evidence metadata для server/storage/file path ключей.
- Добавлены tests на доступы, секции отчёта, redaction и checksum.

## Формат отчёта

Формат: HTML-страница, отдаётся inline с заголовком:

```http
Content-Disposition: inline; filename="document-<id>-evidence-report.html"
```

Секции отчёта:

- Document;
- Organization;
- Versions;
- AI Fields;
- Workflow;
- Exchanges and Messages;
- Audit Events;
- Timeline;
- Report Checksum and Limitations.

Checksum:

- `report_checksum_sha256`;
- считается как SHA-256 от canonical JSON existing sanitized evidence package;
- нужен для внутреннего контроля целостности представления, не является электронной подписью.

## Ограничения отчёта

- Отчёт не заявляет юридическую силу.
- Электронная подпись не добавлялась.
- Blockchain не добавлялся.
- PDF export не добавлялся, чтобы не тянуть тяжёлые зависимости; выбран HTML report.
- Отчёт не включает raw file contents.
- Отчёт не включает secure tokens, token hashes, token hints, portal token URLs, webhook secrets, API keys, private keys, server/storage/file paths.
- Доступ к отчёту идёт через `get_allowed_documents` и `user_can_access_document`.
- Данные других организаций не включаются, так как report строится из существующего evidence package, фильтруемого по organization.

## Изменённые файлы

- `dms/services/evidence.py`
- `dms/services/evidence_report.py`
- `dms/views.py`
- `dms/urls.py`
- `templates/dms/evidence_report.html`
- `templates/dms/document_detail.html`
- `dms/test_legal_evidence_package.py`
- `docs/codex/progress/STAGE_27_PROGRESS.md`

## Миграции

Новых миграций нет.

## Проверки

Выполнено:

```powershell
.\.venv\Scripts\python.exe manage.py test dms.test_legal_evidence_package --verbosity 2
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
git diff --check
git status
```

Результаты:

- Evidence-focused tests: 7 OK.
- `manage.py check`: OK.
- `makemigrations --check --dry-run`: no changes detected.
- `migrate --check`: OK.
- Full `dms` suite: 132 tests OK.
- `git diff --check`: OK, only expected CRLF warnings on Windows.
- Full suite emitted expected warnings for unavailable local Qdrant and HuggingFace unauthenticated model access; tests passed.

## Что нужно проверить вручную

1. Открыть документ с версиями, workflow, exchange и audit events.
2. Нажать `Evidence report`.
3. Проверить, что HTML report читается без скачивания JSON.
4. Проверить секции Document, Versions, AI Fields, Workflow, Exchanges, Audit Events, Timeline.
5. Проверить наличие `Report Checksum`.
6. Проверить, что в отчёте нет secure token, token hash, token hint, portal URL with token, webhook secret, API key, server file path.
7. Проверить, что пользователь другой organization получает 404.
8. Проверить, что `Evidence JSON` продолжает работать как раньше.

## Не сделано намеренно

- Stage 28 не начат.
- ЭЦП не добавлялась.
- Blockchain не добавлялся.
- Юридическая сила отчёта не заявлялась.
