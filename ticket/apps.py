# ticket/apps.py
from django.apps import AppConfig, apps as global_apps
from django.db.models.signals import m2m_changed

class TicketConfig(AppConfig):
    name = "ticket"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # post_save-Receiver etc. laden
        from . import signals  # noqa: F401

