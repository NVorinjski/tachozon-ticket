from django.dispatch import receiver
from django.utils.html import strip_tags
from django.core.files.base import ContentFile
from django.utils import timezone

from django_mailbox.signals import message_received
from django_mailbox.models import Message as MailMessage

from django.contrib.auth import get_user_model
from ticket.models import Ticket, Attachment, ProblemSource # <- ggf. anpassen

User = get_user_model()

def _system_user():
    # Fallback-User für eingehende Mails
    return User.objects.filter(username='mailer').first()

@receiver(message_received)
def handle_incoming_message(sender, message: MailMessage, **kwargs):
    """
    Wird von django-mailbox getriggert, wenn process_incoming_message() aufgerufen wurde.
    `message` ist ein django_mailbox.models.Message-Objekt.
    """
    subject = message.subject or "(kein Betreff)"
    # Bevorzuge reinen Text, sonst HTML → Text
    if message.text:
        notes = message.text
    elif message.html:
        notes = strip_tags(message.html)
    else:
        notes = ""

    try:
        psource = ProblemSource.objects.get(slug='email')
    except ProblemSource.DoesNotExist:
        psource = ProblemSource.objects.first()

    # >>> HIER Feldnamen an DEIN Ticket-Modell anpassen! <<<
    # Beispiel: title, notes, created_by, source, from_email...
    t = Ticket.objects.create(
        title=subject,
        problem_source=psource,
        note=notes,
        created_by=_system_user(),
        created_date=timezone.now()      
    )

    # Attachments mitschieben (wenn dein Attachment-Modell eins hat)
    for att in message.attachments.all():
        # Dateinamen bestimmen
        try:
            fname = att.get_filename() or att.name or "attachment"
        except Exception:
            fname = "attachment"

        content = att.document.read()  # Dateiinhalt aus django-mailbox Attachment
        # >>> HIER Feldnamen anpassen: 'file' und 'ticket' sind Beispiel-Feldnamen
        Attachment.objects.create(
            ticket=t,
            file=ContentFile(content, name=fname)
        )