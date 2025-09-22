# ticket/signals.py
import logging
from django.dispatch import receiver
from django.utils.html import strip_tags
from django.utils import timezone
from django.core.files.base import ContentFile
from email.utils import parseaddr

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

@receiver(message_received)
def handle_incoming_message(sender, message: MailMessage, **kwargs):
    try:
        subject = message.subject or "(kein Betreff)"
        # --- Absender sauber extrahieren ---
        name, addr = parseaddr(message.from_header or "")
        # hübsch formatiert, z. B. "Max Mustermann <max@example.com>"
        if name and addr:
            from_line = f"Von: {name} <{addr}>"
        elif addr:
            from_line = f"Von: {addr}"
        else:
            # Fallback: roher Header, falls nichts geparst werden konnte
            from_line = f"Von: {message.from_header or 'Unbekannt'}"

        # Bevorzuge Plaintext; wenn nur HTML da ist -> Stripped Text.
        if message.text:
            body = message.text
        elif message.html:
            body = strip_tags(message.html)
        else:
            body = ""

        # Absenderzeile oben drüber
        notes = f"{from_line}\n{body}".strip()

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
