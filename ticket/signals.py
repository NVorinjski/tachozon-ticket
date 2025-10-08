# ticket/signals.py
import logging
from email.utils import parseaddr
import html as ihtml
import re

from django.dispatch import receiver
from django.utils import timezone
from django.core.files.base import ContentFile
from django.urls import reverse

from django_mailbox.signals import message_received
from django_mailbox.models import Message as MailMessage

from django.db.models.signals import post_save, m2m_changed, pre_save
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model

from ticket.models import Ticket, ProblemSource, Attachment

log = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------
def _system_user():
    """
    Fallback-User für eingehende Mails:
    - zuerst 'mailer', sonst erster Superuser, sonst erster staff.
    """
    u = User.objects.filter(username="mailer").first()
    if not u:
        u = User.objects.filter(is_superuser=True).first() or User.objects.filter(is_staff=True).first()
    return u


def _normalize_newlines(s: str) -> str:
    # CRLF/CR → LF
    return (s or "").replace("\r\n", "\n").replace("\r", "\n")


def _ticket_url(ticket: Ticket) -> str:
    # Passe ggf. den URL-Namen an
    return reverse("ticket_detail", args=[ticket.pk])


def _notify_channel(group: str, payload: dict):
    """
    Sendet payload an eine Channels-Group.
    """
    if not group:
        return
    channel_layer = get_channel_layer()
    if not channel_layer:
        log.warning("Channel layer not available; skipped notify to group=%s", group)
        return
    async_to_sync(channel_layer.group_send)(group, {"type": "send_notification", "content": payload})


def _notify_user(user, payload: dict):
    """
    Personalisierte Notification an genau einen User.
    """
    if not user:
        return
    group = f"user_{getattr(user, 'id', None)}"
    log.info("WS notify -> user_id=%s title=%s", getattr(user, "id", None), payload.get("title"))
    _notify_channel(group, payload)


def _notify_broadcast(payload: dict):
    """
    Broadcast an alle eingeloggten Tabs (unsere Broadcast-Gruppe).
    """
    log.info("WS broadcast -> title=%s", payload.get("title"))
    _notify_channel("broadcast", payload)


def _team_members(team):
    """
    Liefert Team-Mitglieder als Liste von Usern zurück.
    → Bei 'Team.members' (ManyToMany zu User) funktioniert das out-of-the-box.
      Andernfalls bitte an euer Team-Modell anpassen.
    """
    if not team:
        return []
    if hasattr(team, "members"):
        try:
            return list(team.members.all())
        except Exception:
            return []
    return []


# ---------------------------------------------------------------------
# E-MAIL → Ticket (dein bestehender Flow, minimal gesäubert)
# ---------------------------------------------------------------------
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

        # Body wählen (HTML bevorzugen)
        if message.html:
            body = message.html
            notes = f"<p>{from_line}</p>\n{body}"
        else:
            body = _normalize_newlines(getattr(message, "text", "") or "")
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

        # Attachments mitnehmen
        for att in message.attachments.all():
            try:
                fname = att.get_filename() or att.name or "attachment"
            except Exception:
                fname = "attachment"
            content = att.document.read()
            Attachment.objects.create(ticket=t, file=ContentFile(content, name=fname))

        log.info("Ticket aus Mail %s (#%s) erzeugt", getattr(message, "id", "?"), t.id)

    except Exception as exc:
        log.exception("Ticket-Erzeugung aus Mail %s fehlgeschlagen: %s", getattr(message, "id", "?"), exc)


# ---------------------------------------------------------------------
# Ticket: Create / Update Notifications
# ---------------------------------------------------------------------
@receiver(post_save, sender=Ticket)
def ticket_created_or_updated(sender, instance: Ticket, created, update_fields=None, **kwargs):
    """
    Benachrichtigungen bei Erstellung/Änderung:
      - Neu erstellt:
          * Broadcast an alle eingeloggten Tabs
          * assigned_to (falls gesetzt)
          * optional: Team-Mitglieder
      - Update:
          * assigned_to in update_fields → neuer assigned_to
          * assigned_team in update_fields → Team-Mitglieder

    Hinweis: Für Zuweisungs-Änderungen verwenden wir zusätzlich einen pre_save-Hook (s.u.),
    weil update_fields oft leer ist (je nach Save-Pfad / Form).
    """
    if created:
        # 0) Broadcast an alle
        _notify_broadcast({
            "title": "Neues Ticket",
            "message": f"#{instance.id}: {instance.title}",
            "url": _ticket_url(instance),
            "level": "info",
        })

        # 1) persönlich an assigned_to
        if getattr(instance, "assigned_to", None):
            _notify_user(
                instance.assigned_to,
                {
                    "title": "Dir zugewiesen (neu)",
                    "message": f"#{instance.id}: {instance.title}",
                    "url": _ticket_url(instance),
                    "level": "info",
                },
            )

        # 2) optional Team
        if getattr(instance, "assigned_team", None):
            for u in _team_members(instance.assigned_team):
                _notify_user(
                    u,
                    {
                        "title": "Neues Team-Ticket",
                        "message": f"#{instance.id}: {instance.title} (Team: {instance.assigned_team})",
                        "url": _ticket_url(instance),
                        "level": "info",
                    },
                )
        return

    # Selektive Updates (falls update_fields gesetzt ist)
    if update_fields:
        if "assigned_to" in update_fields and getattr(instance, "assigned_to", None):
            _notify_user(
                instance.assigned_to,
                {
                    "title": "Ticket zugewiesen",
                    "message": f"#{instance.id}: {instance.title}",
                    "url": _ticket_url(instance),
                    "level": "info",
                },
            )

        if "assigned_team" in update_fields and getattr(instance, "assigned_team", None):
            for u in _team_members(instance.assigned_team):
                _notify_user(
                    u,
                    {
                        "title": "Team-Zuweisung aktualisiert",
                        "message": f"#{instance.id}: {instance.title} (Team: {instance.assigned_team})",
                        "url": _ticket_url(instance),
                        "level": "info",
                    },
                )


# Robust gegen „update_fields ist leer“: Alt/Neu von assigned_to erkennen
@receiver(pre_save, sender=Ticket)
def _detect_assigned_to_change(sender, instance: Ticket, **kwargs):
    if not instance.pk:
        return
    try:
        prev = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return

    prev_id = getattr(prev, "assigned_to_id", None)
    new_id = getattr(instance, "assigned_to_id", None)

    if prev_id != new_id and new_id:
        _notify_user(
            instance.assigned_to,
            {
                "title": "Ticket zugewiesen",
                "message": f"#{instance.id}: {instance.title}",
                "url": _ticket_url(instance),
                "level": "info",
            },
        )


# ---------------------------------------------------------------------
# M2M: Co-Assignees hinzugefügt → persönliche Pings
# ---------------------------------------------------------------------
@receiver(m2m_changed, sender=Ticket.co_assignees.through)
def co_assignees_changed(sender, instance: Ticket, action, pk_set, **kwargs):
    if action != "post_add" or not pk_set:
        return
    for user in User.objects.filter(pk__in=pk_set):
        _notify_user(
            user,
            {
                "title": "Als Mitbearbeiter hinzugefügt",
                "message": f"#{instance.id}: {instance.title}",
                "url": _ticket_url(instance),
                "level": "info",
            },
        )
