@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"

set "APP_HOST=127.0.0.1"
set "APP_PORT=8001"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"

if not exist ".env" (
    echo [ERROR] .env not found.
    echo Create .env from .env.example and set local secrets before starting DocFlow.
    pause
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python virtual environment not found: %PYTHON_EXE%
    echo Create it and install dependencies:
    echo   python -m venv .venv
    echo   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

docker compose version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Compose is not available.
    echo Start Docker Desktop and try again.
    pause
    exit /b 1
)

echo [1/5] Starting PostgreSQL, Redis and Qdrant...
docker compose --env-file .env up -d db redis qdrant
if errorlevel 1 (
    echo [ERROR] Infrastructure startup failed.
    pause
    exit /b 1
)

set "DJANGO_DEBUG=True"
set "DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost"
set "DJANGO_CSRF_TRUSTED_ORIGINS=http://127.0.0.1:%APP_PORT%,http://localhost:%APP_PORT%"
set "POSTGRES_HOST=localhost"
set "QDRANT_HOST=localhost"
set "REDIS_URL=redis://localhost:6379/0"
set "CELERY_BROKER_URL=redis://localhost:6379/0"
set "CELERY_RESULT_BACKEND=redis://localhost:6379/0"

echo [2/5] Waiting for database...
docker compose --env-file .env exec -T db pg_isready -U "%POSTGRES_USER%" -d "%POSTGRES_DB%" >nul 2>&1
if errorlevel 1 (
    timeout /t 5 /nobreak >nul
)

echo [3/5] Running Django system check...
"%PYTHON_EXE%" manage.py check
if errorlevel 1 (
    echo [ERROR] Django check failed.
    pause
    exit /b 1
)

echo [4/5] Applying migrations...
"%PYTHON_EXE%" manage.py migrate
if errorlevel 1 (
    echo [ERROR] Django migrate failed.
    pause
    exit /b 1
)

echo [5/5] Starting Django development server...
echo.
echo DocFlow is starting at: http://%APP_HOST%:%APP_PORT%/
echo Health check:           http://%APP_HOST%:%APP_PORT%/health/
echo.
echo Keep this window open while working. Press CTRL+C to stop Django.
echo Docker services can be stopped with: docker compose --env-file .env stop
echo.

start "" "http://%APP_HOST%:%APP_PORT%/"
"%PYTHON_EXE%" manage.py runserver "%APP_HOST%:%APP_PORT%"

endlocal
