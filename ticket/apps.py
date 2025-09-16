from django.apps import AppConfig
class TicketConfig(AppConfig):
    name = 'ticket'
    def ready(self):
        from . import signals  # noqa
