# ticket/tasks.py
import logging

from background_task import background
from django.conf import settings
from django.contrib.auth.models import User

from huey import crontab
from huey.contrib.djhuey import periodic_task

# Optionaler Lock-Decorator (verhindert Überschneidungen). Falls in deiner djhuey-Version nicht vorhanden,
# fällt er einfach auf einen No-Op zurück.
try:
    from huey.contrib.djhuey import lock_task  # type: ignore
except Exception:  # pragma: no cover
    def lock_task(name, expire=None):
        def _wrap(fn):
            return fn
        return _wrap

from authentication.graph_api.base import GraphAPI
from authentication.models import MicrosoftProfile
from ticket.models import Analytics

# Mail-Import Logik (OAuth2/IMAP) – kommt aus unserer neuen Hilfsdatei
from .mail_ingest import fetch_and_store

logger = logging.getLogger(__name__)


@background(schedule=1)
def update_analytics_in_background():
    print("UPDATING ANALYTICS")
    Analytics.update_tickets_per_problem_source()
    Analytics.update_tickets_per_day()


def update_analytics_in_development():
    print("UPDATING ANALYTICS")
    Analytics.update_tickets_per_problem_source()
    Analytics.update_tickets_per_day()


def manual_update_analytics():
    if settings.DEBUG:
        update_analytics_in_development()
    else:
        update_analytics_in_background()


@periodic_task(crontab(minute=30, hour="*/12"))
def daily_user_update():
    update_users()


@periodic_task(crontab(hour='12', day_of_week='0'))
def weekly_completed_task_cleanup():
    from background_task.models import CompletedTask
    CompletedTask.objects.all().delete()


# Update analytics every 10 minutes between 5-19 Uhr Monday-Saturday
@periodic_task(crontab(minute="*/10", hour='5-19', day_of_week='1,2,3,4,5,6'))
def update_analytics():
    Analytics.update_tickets_per_day()
    Analytics.update_tickets_per_problem_source()


def update_users():
    graph_api = GraphAPI()
    users = graph_api.get_all_users()
    for user in users:
        name = user["displayName"]
        email = user["mail"] if user["mail"] else user["userPrincipalName"]
        id = user["id"]
        new_user, created = User.objects.update_or_create(
            username=email,
            defaults={
                "email": email,
            }
        )
        MicrosoftProfile.objects.update_or_create(
            user=new_user,
            defaults={"ms_id": id})
        if created:
            new_user.first_name = name
            new_user.set_password(email)
            new_user.save()
            print("NEW USER CREATED:", name)


# --- NEU: Periodisches Mail-Polling alle 5 Minuten ---
ENABLE_MAIL_POLL = bool(getattr(settings, "MAIL_POLL_ENABLED", True))

def _poll_support_mailbox_impl():
    """
    Pollt das Support-Postfach via OAuth2/IMAP und importiert Mails in django-mailbox
    (inkl. Attachments & Ticket-Erzeugung über Signals). Importierte Mails werden als \Seen markiert.
    """
    from .mail_ingest import fetch_and_store  # lazy import, falls Settings/Imports variieren
    try:
        count = fetch_and_store(
            mailbox_name="Support",
            folder=None,        # z.B. "INBOX/Support"
            mark_seen=True,     # importierte Mails als gelesen markieren
            dry_run=False,      # produktiv speichern
            limit=None,         # z.B. 50, falls du drosseln willst
        )
        logger.info("Mail poll finished: imported %s message(s)", count or 0)
    except Exception as exc:
        logger.exception("Mail poll failed: %s", exc)

if ENABLE_MAIL_POLL:
    @lock_task('mail-poll-lock')           # verhindert Überschneidungen
    @periodic_task(crontab(minute='*/5'))  # alle 5 Minuten
    def poll_support_mailbox():
        _poll_support_mailbox_impl()
else:
    # Nicht geplant – aber manuell aufrufbar (z.B. in der Shell) und gut logbar.
    def poll_support_mailbox():
        logger.info("Mail poll skipped: MAIL_POLL_ENABLED is False")
        return
