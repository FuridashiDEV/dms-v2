# Stage 28 — Email Ingestion / Приём документов из почты

## Цель этапа

Добавить первый реальный канал поступления документов извне — электронную почту.

На этом этапе нужна минимальная основа, а не полноценный почтовый клиент.

## Что добавить

Добавить foundation для email ingestion:

- модель или настройки email connection, если нужно;
- задачу получения писем;
- извлечение вложений;
- создание Document из вложения;
- создание DocumentVersion;
- сохранение metadata письма;
- связь документа с письмом через ExternalReference или отдельную безопасную связь.

## Как должно работать

Письмо с вложением приходит на подключённый ящик.

Система:

1. Получает письмо.
2. Извлекает вложение.
3. Проверяет файл через upload validation.
4. Создаёт обычный Document.
5. Создаёт DocumentVersion.
6. Сохраняет sender, subject, received_at, message_id.
7. Не создаёт дубль при повторной обработке.

## Безопасность

Запрещено хранить пароль почты в открытом JSON.

Credentials должны храниться безопасно или через environment-backed secrets.

## Чего нельзя делать

- Не делать полноценный почтовый клиент.
- Не удалять письма из ящика автоматически.
- Не обрабатывать все вложения без фильтров.
- Не хранить пароли в открытом виде.
- Не начинать Stage 29.

## Тесты

Добавить tests:

1. Email attachment creates Document.
2. DocumentVersion is created.
3. Duplicate message_id does not create duplicate document.
4. Unsafe attachment is rejected.
5. Organization isolation is preserved.
6. Credentials are not stored in plaintext JSON.

## Проверки

Выполнить:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test dms --verbosity 1
git diff --check
git status