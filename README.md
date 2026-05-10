# AI Document Archive

Интеллектуальный электронный архив документов на Django с OCR, AI-разбором, семантическим поиском и архивными метаданными.

## Что умеет система

- Иерархия отделов и папок
- Загрузка и хранение документов с карточкой архива
- OCR и извлечение текста из PDF, изображений и офисных форматов
- AI-сводка документа и похожие документы
- Версионность и постоянный `public_id`
- Семантический поиск через Qdrant
- Архивные метаданные: язык, автор, retention, checksum, MIME type, format risk
- Связи между документами

## Стек

- Django 6
- PostgreSQL
- Qdrant
- Ollama
- Tesseract OCR

## Быстрый локальный запуск

1. Создайте `.env` из [`.env.example`](D:/Projects/uni_dms/.env.example).
2. Установите Python-зависимости:

```powershell
pip install -r requirements.txt
```

3. Поднимите PostgreSQL и Qdrant.
4. Убедитесь, что Ollama запущена и модель `mistral` загружена:

```powershell
ollama pull mistral
```

5. Выполните миграции и запустите сервер:

```powershell
python manage.py migrate
python manage.py runserver
```

## Docker

Для инфраструктуры можно использовать [docker-compose.yml](D:/Projects/uni_dms/docker-compose.yml):

```powershell
docker compose up -d db qdrant
```

Если нужен полный Docker-запуск:

```powershell
docker compose up --build
```

## Переменные окружения

Смотрите [`.env.example`](D:/Projects/uni_dms/.env.example). Основные:

- `POSTGRES_*`
- `QDRANT_*`
- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `DJANGO_TIME_ZONE`
- `DJANGO_LOG_LEVEL`

## Проверка перед демо

```powershell
python manage.py check
python manage.py migrate
python manage.py test dms --keepdb --noinput
```

## Подготовка демо-данных

Чтобы очистить старые данные и собрать красивый презентационный набор документов, выполните:

```powershell
python manage.py prepare_demo_data
```

Команда:

- удаляет старые документы, папки, типы и несистемных пользователей;
- создает демо-структуру архива;
- наполняет систему версиями, связями, доступами и журналом действий;
- переиндексирует документы в Qdrant, если он доступен.

## Демо-сценарий

Подробный runbook лежит в [docs/DEMO_RUNBOOK.md](D:/Projects/uni_dms/docs/DEMO_RUNBOOK.md).
Короткий pitch deck: [docs/CLIENT_PITCH_DECK.md](D:/Projects/uni_dms/docs/CLIENT_PITCH_DECK.md).
Короткий demo script: [docs/CLIENT_DEMO_SCRIPT.md](D:/Projects/uni_dms/docs/CLIENT_DEMO_SCRIPT.md).
