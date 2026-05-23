# DocFlow Demo Dataset

Demo dataset создается management command:

```powershell
.\.venv\Scripts\python.exe manage.py prepare_demo_data --skip-vectors
```

Команда идемпотентна: она очищает только demo organization `demo-university` и не трогает другие организации.

## Demo users

- `demo_admin / DemoArchive2026!` - администратор demo organization.
- `demo_legal / DemoArchive2026!` - юридический отдел.
- `demo_finance / DemoArchive2026!` - финансы.
- `demo_academic / DemoArchive2026!` - академический офис.
- `demo_archive / DemoArchive2026!` - архив.
- `demo_approver / DemoArchive2026!` - согласующий.

## Какие данные создаются

- Business chain: договор, приложение, акт, счет, дополнительное соглашение.
- Университетский сценарий: регламент академической мобильности, чеклист, file plan.
- Медицина: synthetic clinic supply contract без patient data.
- Бизнес: synthetic consulting invoice.
- Квазигос: mixed-language status report.
- Версии документов, связи, workflow, B2B exchange, messages, audit events, usage events, AI review suggestions, import batch.

## Safety

- Нет реальных персональных данных.
- Нет реальных документов клиентов.
- Email/domain используют `example.test`.
- Телефон и counterparty данные synthetic.
- Secure external token печатается только для локального demo сценария и не должен попадать в публичные материалы.

## Semantic indexing

По умолчанию для быстрого безопасного демо используйте `--skip-vectors`. Для демонстрации смыслового поиска на локальном Qdrant можно запустить без флага, если Qdrant и модельный стек готовы:

```powershell
.\.venv\Scripts\python.exe manage.py prepare_demo_data
```

Если Qdrant недоступен, команда пропускает vector indexing для отдельных документов и оставляет базовый поиск работоспособным.
