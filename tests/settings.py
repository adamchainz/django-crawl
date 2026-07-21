from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

SECRET_KEY = "NOTASECRET"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
}

ROOT_URLCONF = "tests.urls"

TIME_ZONE = "UTC"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "django_crawl",
]

STATIC_URL = "/static/"

STATICFILES_DIRS = [BASE_DIR / "tests/static"]

USE_TZ = True
