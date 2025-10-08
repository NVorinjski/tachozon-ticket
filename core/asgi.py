# core/asgi.py
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.prod")

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.urls import path
from ticket.consumers import NotificationConsumer

# Django-ASGI nur als http-Teil
django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter([
            path("ws/notifications/", NotificationConsumer.as_asgi()),
        ])
    ),
})
