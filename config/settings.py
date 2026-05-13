import os
import re
from pathlib import Path

from django.utils.translation import gettext_lazy as _


BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env_file(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


DEBUG = env_bool("DJANGO_DEBUG", False)
DEBUG_PROPAGATE_EXCEPTIONS = DEBUG

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-local-dev-only"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY is required when DJANGO_DEBUG=False")

ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS",
    ["127.0.0.1", "localhost"],
)
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])

AUTH_USER_MODEL = "dms.User"

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", not DEBUG)
SESSION_COOKIE_AGE = int(os.getenv("DJANGO_SESSION_COOKIE_AGE", "1800"))
SESSION_EXPIRE_AT_BROWSER_CLOSE = env_bool("DJANGO_SESSION_EXPIRE_AT_BROWSER_CLOSE", True)
SESSION_SAVE_EVERY_REQUEST = env_bool("DJANGO_SESSION_SAVE_EVERY_REQUEST", True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = env_bool("DJANGO_USE_X_FORWARDED_HOST", False)
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "SAMEORIGIN"
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 0 if DEBUG else 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", not DEBUG)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", not DEBUG)

LOGIN_RATE_LIMIT_ATTEMPTS = env_int("DJANGO_LOGIN_RATE_LIMIT_ATTEMPTS", 5)
LOGIN_RATE_LIMIT_WINDOW = env_int("DJANGO_LOGIN_RATE_LIMIT_WINDOW", 900)


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "mptt",
    "dms",
    "pgvector.django",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "uni-dms-cache",
    }
}

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "dms.context_processors.notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "dms"),
        "USER": os.getenv("POSTGRES_USER", "postgres"),
        "PASSWORD": (
            os.getenv("POSTGRES_PASSWORD")
            or ("12345678" if DEBUG else None)
        ),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": env_int("POSTGRES_CONN_MAX_AGE", 60),
        "CONN_HEALTH_CHECKS": env_bool("POSTGRES_CONN_HEALTH_CHECKS", True),
    }
}

if not DATABASES["default"]["PASSWORD"]:
    raise RuntimeError("POSTGRES_PASSWORD is required when DJANGO_DEBUG=False")


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


LANGUAGE_CODE = "ru"
LANGUAGES = [
    ("ru", _("Russian")),
    ("kk", _("Kazakh")),
    ("en", _("English")),
]
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "Asia/Qyzylorda")
USE_I18N = True
USE_TZ = True


DATA_UPLOAD_MAX_MEMORY_SIZE = env_int("DJANGO_DATA_UPLOAD_MAX_MEMORY_SIZE", 50 * 1024 * 1024)
FILE_UPLOAD_MAX_MEMORY_SIZE = env_int("DJANGO_FILE_UPLOAD_MAX_MEMORY_SIZE", 50 * 1024 * 1024)
FILE_UPLOAD_PERMISSIONS = 0o640


STATIC_URL = os.getenv("DJANGO_STATIC_URL", "static/")
STATIC_ROOT = Path(os.getenv("DJANGO_STATIC_ROOT", BASE_DIR / "staticfiles"))

MEDIA_URL = os.getenv("DJANGO_MEDIA_URL", "/media/")
MEDIA_ROOT = Path(os.getenv("DJANGO_MEDIA_ROOT", BASE_DIR / "media"))

LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

LOG_DIR = Path(os.getenv("DJANGO_LOG_DIR", BASE_DIR))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_LEVEL = os.getenv("DJANGO_LOG_LEVEL", "INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        },
    },
    "handlers": {
        "file": {
            "level": LOG_LEVEL,
            "class": "logging.FileHandler",
            "filename": LOG_DIR / os.getenv("DJANGO_LOG_FILE", "errors.log"),
            "formatter": "standard",
        },
        "console": {
            "level": LOG_LEVEL,
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["file", "console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "dms": {
            "handlers": ["file", "console"],
            "level": LOG_LEVEL,
            "propagate": False,
        }
    },
}


SEARCH_EMBEDDING_MODEL = os.getenv("SEARCH_EMBEDDING_MODEL", "BAAI/bge-m3")
SEARCH_EMBEDDING_DIMENSIONS = {
    "all-MiniLM-L6-v2": 384,
    "BAAI/bge-m3": 1024,
    "intfloat/multilingual-e5-large": 1024,
}
SEARCH_EMBEDDING_VECTOR_SIZE = env_int(
    "SEARCH_EMBEDDING_VECTOR_SIZE",
    SEARCH_EMBEDDING_DIMENSIONS.get(SEARCH_EMBEDDING_MODEL, 384),
)
SEARCH_INDEX_VERSION = env_int("SEARCH_INDEX_VERSION", 2)
SEARCH_QDRANT_COLLECTION_BASE = os.getenv("SEARCH_QDRANT_COLLECTION_BASE", "documents")
SEARCH_EMBEDDING_COLLECTION_SUFFIX = re.sub(r"[^a-z0-9]+", "_", SEARCH_EMBEDDING_MODEL.lower()).strip("_")

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = env_int("QDRANT_PORT", 6333)
QDRANT_COLLECTION = os.getenv(
    "QDRANT_COLLECTION",
    f"{SEARCH_QDRANT_COLLECTION_BASE}_{SEARCH_EMBEDDING_COLLECTION_SUFFIX}",
)
QDRANT_HEALTH_CHECK = env_bool("QDRANT_HEALTH_CHECK", False)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)

HEALTH_CHECK_DATABASE = env_bool("HEALTH_CHECK_DATABASE", True)
HEALTH_CHECK_QDRANT = env_bool("HEALTH_CHECK_QDRANT", QDRANT_HEALTH_CHECK)
