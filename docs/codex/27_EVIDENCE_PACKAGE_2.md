# Stage 27 — Evidence Package 2.0 / Доказательный пакет 2.0

## Цель этапа

Сделать доказательный пакет более понятным для пользователя.

Сейчас evidence export существует как JSON. Нужно добавить человекочитаемый отчёт.

## Что добавить

Добавить PDF или HTML-представление доказательного отчёта.

Минимальные секции:

- сведения о документе;
- организация;
- версии;
- ИИ-поля;
- согласования;
- обмены;
- сообщения;
- аудит;
- хронология событий;
- контрольная сумма отчёта.

Если PDF требует тяжёлой зависимости, сначала сделать HTML report или downloadable HTML.

## Безопасность

Отчёт не должен включать:

- raw secure tokens;
- token hashes;
- token hints;
- portal URLs with token;
- webhook secrets;
- API keys;
- server file paths;
- raw file contents.

Использовать existing evidence redaction.

## Права доступа

Отчёт доступен только пользователю, который имеет доступ к документу.

## Чего нельзя делать

- Не заявлять юридическую силу.
- Не добавлять электронную подпись.
- Не добавлять blockchain.
- Не раскрывать секреты.
- Не начинать Stage 28.

## Тесты

Добавить tests:

1. Authorized user can open evidence report.
2. Unauthorized user cannot open evidence report.
3. Report includes document/versions/audit/exchange sections.
4. Report does not include secrets/tokens.
5. Report checksum is present if implemented.

## Проверки

Выполнить:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
git diff --check
git status