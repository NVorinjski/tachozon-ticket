from huey import SqliteHuey

from core.settings.common import *

import os

DEBUG = True
PROD = True #if not DEBUG else False

INSTALLED_APPS.append('huey.contrib.djhuey')

DATABASES = {
    'default': {
        'ENGINE': os.getenv("POSTGRES_BACKEND", "postgres"),
        'NAME': os.getenv("POSTGRES_NAME", "postgres"),
        'USER': os.getenv("POSTGRES_USER", "postgres"),
        'PASSWORD': os.getenv("POSTGRES_PASSWORD", "postgres"),
        'HOST': os.getenv("POSTGRES_HOST", "postgres"),
        'PORT': os.getenv("POSTGRES_PORT", "postgres"),
        'CONN_MAX_AGE': int(os.getenv("DJANGO_DB_CONN_MAX_AGE", "60"))
    }
}

HUEY = SqliteHuey(name='huey.db')

USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

_server = os.getenv('SERVER', 'ticket.tachozon.com').strip()
CSRF_TRUSTED_ORIGINS = [f"https://{_server}"]

ALLOWED_HOSTS = ['localhost', '127.0.0.1', _server]

ASGI_APPLICATION = "core.asgi.application"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [("redis", 6379)]},  # Hostname wie im compose
    }
}