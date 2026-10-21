"""Configuración para desarrollo local de DO IT UNAM."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-local-development-only")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",")
    if host.strip()
]
PUBLIC_TUNNEL_ENABLED = os.environ.get("DJANGO_PUBLIC_TUNNEL") == "1"
if PUBLIC_TUNNEL_ENABLED:
    ALLOWED_HOSTS.append(".trycloudflare.com")
CSRF_TRUSTED_ORIGINS = ["https://*.trycloudflare.com"] if PUBLIC_TUNNEL_ENABLED else []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "editor.apps.EditorConfig",
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

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

if os.environ.get("POSTGRES_DB", "").strip():
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"].strip(),
            "USER": os.environ.get("POSTGRES_USER", "postgres").strip(),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1").strip(),
            "PORT": os.environ.get("POSTGRES_PORT", "5432").strip(),
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    # SQLite conserva el arranque inmediato de desarrollo. Definir POSTGRES_DB
    # cambia el proyecto completo a PostgreSQL sin tocar el código.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "editor.auth_backend.InstitutionalRoleBackend",
]

LANGUAGE_CODE = "es-mx"
TIME_ZONE = "America/Mexico_City"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "editor:index"
LOGOUT_REDIRECT_URL = "login"

# Gemini se usa exclusivamente desde el servidor. La clave nunca se envía al navegador.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_TEXT_MODEL = os.environ.get("GEMINI_TEXT_MODEL", "gemini-flash-latest").strip()
GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image").strip()
try:
    GEMINI_DAILY_TOKEN_LIMIT = max(1, int(os.environ.get("GEMINI_DAILY_TOKEN_LIMIT", "100000")))
except ValueError:
    GEMINI_DAILY_TOKEN_LIMIT = 100000

INSTITUTIONAL_EMAIL_DOMAINS = tuple(
    domain.strip().lower()
    for domain in os.environ.get("INSTITUTIONAL_EMAIL_DOMAINS", "comunidad.unam.mx").split(",")
    if domain.strip()
)
ALLOW_LEGACY_USERNAME_LOGIN = os.environ.get("ALLOW_LEGACY_USERNAME_LOGIN", "1") == "1"

EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_DEFAULT_FROM_EMAIL", "no-responder@doit-unam.local")

# Conversión de documentos. En desarrollo puede ejecutarse en el mismo proceso;
# en despliegue se desactiva ALWAYS_EAGER y un worker consume la cola de Redis.
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "1") == "1"
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_SOFT_TIME_LIMIT = 14 * 60
CELERY_TASK_TIME_LIMIT = 15 * 60
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 30 * 60}
MAX_DOCUMENT_UPLOAD_SIZE = 50 * 1024 * 1024
