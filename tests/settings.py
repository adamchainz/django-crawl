from __future__ import annotations

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
    "django_crawl",
]

USE_TZ = True
