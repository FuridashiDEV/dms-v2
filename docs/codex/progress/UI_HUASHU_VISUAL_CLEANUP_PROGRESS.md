# UI Huashu Visual Cleanup Progress

## Статус

Выполнено на ветке `visual-huashu-polish`.

Цель этапа: убрать визуальный шум, mojibake, университетский/AI-slop copy и чрезмерно тяжёлые шрифты на ключевых пользовательских и операционных экранах без изменения бизнес-логики.

## Проверенные templates

- `templates/base.html`
- `templates/auth/login.html`
- `templates/dms/dashboard.html`
- `templates/dms/document_list.html`
- `templates/dms/document_detail.html`
- `templates/dms/document_form.html`
- `templates/dms/folder_list.html`
- `templates/dms/user_create.html`
- `templates/dms/analytics_dashboard.html`
- `templates/dms/cost_optimization_dashboard.html`
- `templates/dms/security_dashboard.html`
- `templates/dms/evidence_report.html`

## Найденные UI-проблемы

- Верхняя навигация выходила за доступную ширину на desktop.
- На странице входа оставались устаревшие университетские тексты и декоративная визуальная подача.
- В `user_create.html` был mojibake и тяжёлые inline-стили.
- На части экранов были слишком тяжёлые font-weight значения `800-1000`, из-за чего интерфейс выглядел как сгенерированный шаблон.
- Таблицы в операционных отчётах могли ломать ширину контейнера.
- В документной карточке были остатки mojibake в строках обмена.
- На форме документа был некорректный текст состояния файла.

## Изменённые templates

- `templates/auth/login.html`: полностью очищен экран входа, заменён copy на DocFlow / "Название вашей компании", добавлен спокойный enterprise layout с реальным логотипом.
- `templates/base.html`: стабилизирована шапка, добавлены ограничения nav-label, responsive правила, единые `alert`, `field-error`, `field-help`, `form-actions`, безопасный overflow таблиц.
- `templates/dms/user_create.html`: заменён mojibake на нормальный русский интерфейс, сохранена текущая форма и action flow.
- `templates/dms/dashboard.html`: снижена визуальная тяжесть заголовков и карточек.
- `templates/dms/document_list.html`: упрощены hero/card styles, снижена декоративность, сохранены search/filter flows.
- `templates/dms/document_detail.html`: исправлен mojibake в exchange metadata, снижена визуальная тяжесть карточек.
- `templates/dms/document_form.html`: исправлен текст "Файл не выбран", снижены чрезмерные веса.
- `templates/dms/folder_list.html`: снижены чрезмерные веса заголовков, badges и карточек.
- `templates/dms/analytics_dashboard.html`: унифицирован alert badge.
- `templates/dms/cost_optimization_dashboard.html`: упрощены пользовательские labels, таблицы обёрнуты в overflow container.
- `templates/dms/evidence_report.html`: таблицы обёрнуты в overflow container.

## Добавленные snapshots

- `docs/codex/progress/ui_snapshots/01_login_desktop.png`
- `docs/codex/progress/ui_snapshots/02_dashboard_desktop.png`
- `docs/codex/progress/ui_snapshots/03_search_desktop.png`
- `docs/codex/progress/ui_snapshots/04_document_detail_desktop.png`
- `docs/codex/progress/ui_snapshots/05_document_detail_mobile.png`

## Что намеренно не менялось

- Search core, Qdrant, embeddings, reranking, indexing, entity extraction.
- Permissions, organization isolation, roles, document access.
- Upload flow, document detail/list routes, evidence export, billing, AI processing.
- Django models, migrations, database schema.
- Существующие старые незавершённые изменения в `dms/urls.py`, `dms/views.py`, stage docs и `templates/marketing/`.

## Проверки

- `.\.venv\Scripts\python.exe manage.py check` — passed.
- `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` — passed, no changes detected.
- `.\.venv\Scripts\python.exe manage.py migrate --check` — passed.
- `.\.venv\Scripts\python.exe manage.py test dms --verbosity 1` — passed, 263 tests.
- `git diff --check` — passed.
- `git status --short --branch` — checked; unrelated pre-existing dirty files remain outside the UI cleanup scope.

## Rollback

Если визуал не понравится, изменения можно вернуть точно:

1. Если коммит уже создан: `git revert <UI_CLEANUP_COMMIT_HASH>`.
2. Если нужно просто уйти от ветки: `git switch pilot-ready-enterprise-mvp`.
3. В этой ветке не затрагивались бизнес-логика, модели и миграции, поэтому rollback не требует database rollback.

## Ручная проверка

- Войти как admin и обычный employee.
- Проверить шапку на ширинах 1280px, 1024px, 390px.
- Проверить поиск с результатами и пустой выдачей.
- Проверить карточку документа, загрузку документа, страницу создания пользователя.
- Проверить, что staff-only технические блоки не видны обычному пользователю.
