# ticket/signals.py
import logging
from django.dispatch import receiver
from django.utils.html import strip_tags
from django.utils import timezone
from django.core.files.base import ContentFile
from email.utils import parseaddr
import html as ihtml
import re

from django_mailbox.signals import message_received
from django_mailbox.models import Message as MailMessage

from ticket.models import Ticket, ProblemSource, Attachment
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

def _system_user():
    # Fallback, wenn "mailer" nicht existiert
    u = User.objects.filter(username="mailer").first()
    if not u:
        # notfalls den ersten Superuser oder staff nehmen
        u = User.objects.filter(is_superuser=True).first() or User.objects.filter(is_staff=True).first()
    return u

def _normalize_newlines(s: str) -> str:
    # CRLF/CR → LF, doppelte Leerzeilen nicht aggressiv entfernen
    return s.replace('\r\n', '\n').replace('\r', '\n')

@receiver(message_received)
def handle_incoming_message(sender, message: MailMessage, **kwargs):
    try:
        subject = message.subject or "(kein Betreff)"

        name, addr = parseaddr(message.from_header or "")
        if name and addr:
            from_line = f"Von: {name} <{addr}>"
        elif addr:
            from_line = f"Von: {addr}"
        else:
            from_line = f"Von: {message.from_header or 'Unbekannt'}"

        # Body wählen
        if message.html:  # HTML bevorzugen, unverändert speichern
            body = message.html
            # die Absenderzeile als eigener Absatz voranstellen
            notes = f"<p>{from_line}</p>\n{body}"
        else:
            # Fallback: reiner Text -> nur Newlines normalisieren
            body = _normalize_newlines(message.text or "")
            notes = f"{from_line}\n\n{body}".strip()


        try:
            psource = ProblemSource.objects.get(slug="email")
        except ProblemSource.DoesNotExist:
            psource = ProblemSource.objects.first()

        t = Ticket.objects.create(
            title=subject,
            problem_source=psource,
            note=notes,
            created_by=_system_user(),
            created_date=timezone.now(),
        )

        # Attachments mitschieben
        for att in message.attachments.all():
            try:
                fname = att.get_filename() or att.name or "attachment"
            except Exception:
                fname = "attachment"
            content = att.document.read()  # Dateiinhalt aus django-mailbox
            Attachment.objects.create(
                ticket=t,
                file=ContentFile(content, name=fname),
            )

        logger.info("Ticket aus Mail %s (#%s) erzeugt", message.id, t.id)
    except Exception as exc:
        logger.exception("Ticket-Erzeugung aus Mail %s fehlgeschlagen: %s", getattr(message, "id", "?"), exc)
