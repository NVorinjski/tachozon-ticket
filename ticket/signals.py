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

def _html_to_text_preserving_structure(html: str) -> str:
    """
    Schlanke HTML→Text-Umwandlung mit Absätzen/Zeilenumbrüchen/Listen.
    Keine externen Pakete nötig; ausreichend für Outlook/typische Mails.
    """
    if not html:
        return ""

    # 1) Zeilenumbrüche für Blockelemente
    block_tags_break_before = r'(</?(p|div|h[1-6]|section|article|blockquote|table|tr|ul|ol)\b[^>]*>)'
    html = re.sub(block_tags_break_before, r'\n\1', html, flags=re.I)

    # 2) <br> → Zeilenumbruch
    html = re.sub(r'<br\s*/?>', '\n', html, flags=re.I)

    # 3) Listenelemente als Bullet Points
    #    - li close → newline, li open → "- " (wenn nicht schon Zeilenanfang)
    html = re.sub(r'</li\s*>', '\n', html, flags=re.I)
    html = re.sub(r'<li\b[^>]*>', '\n- ', html, flags=re.I)

    # 4) Tabellenzellen etwas trennen
    html = re.sub(r'</t[hd]\s*>', '\t', html, flags=re.I)

    # 5) Tags entfernen
    text = re.sub(r'<[^>]+>', '', html)

    # 6) HTML Entities auflösen & Newlines normalisieren
    text = ihtml.unescape(text)
    text = _normalize_newlines(text)

    # 7) Mehrfache Leerzeilen minimal glätten (max. 2 in Folge)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 8) Trimmen
    return text.strip()

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
        if message.text:
            body = _normalize_newlines(message.text)
        elif message.html:
            body = _html_to_text_preserving_structure(message.html)
        else:
            body = ""

        # Absenderzeile oben drüber
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
