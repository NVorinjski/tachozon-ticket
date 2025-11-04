import random

from django.contrib.auth.models import User
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View

from ticket.forms import SearchUsersForm, CreateTicketForm, PauseTicketForm
from ticket.models import Attachment, Ticket, Comment, ProblemSource
from ticket.services import TicketEventService
from ticket.tasks import manual_update_analytics
from ticket.thanks import thanks_comments

from authentication.models import Team


class TicketDetailView(View):

    # ----- Berechtigungen -----
    def user_has_full_access(self, user, ticket) -> bool:
        """Darf Details sehen (aber nicht zwingend verwalten)."""
        if not user.is_authenticated:
            return False
        if user == ticket.created_by:
            return True
        if ticket.assigned_to_id == user.id:
            return True
        if ticket.co_assignees.filter(pk=user.pk).exists():
            return True
        if ticket.assigned_team_id and ticket.assigned_team.members.filter(pk=user.pk).exists():
            return True
        return False

    def user_can_manage(self, user, ticket) -> bool:
        """Darf mutierende Aktionen ausführen (nur Hauptbearbeiter)."""
        return user.is_authenticated and ticket.assigned_to_id == user.id

    # ----- GET -----
    def get(self, request, *args, **kwargs):
        ticket = self.get_ticket()
        user = request.user

        # === AUTO-ZUWEISUNG an ersten Öffner, wenn noch niemand zugewiesen ist ===
        if not ticket.assigned_to_id and user.is_authenticated:
            ticket.assigned_to = user
            ticket.save()
            # Event direkt nach der Zuweisung
            TicketEventService(ticket=ticket, current_user=user).create_assign_events(is_automatic=True)

        # Ab hier normal weiter
        has_access = self.user_has_full_access(user, ticket)
        can_manage = self.user_can_manage(user, ticket)

        # Kein Vollzugriff: nur Hinweis
        if not has_access:
            return render(
                request=request,
                template_name='ticket/ticket_detail.html',
                context={
                    "ticket": ticket,
                    "has_access": False,
                    "can_manage": False,
                }
            )

        # Vollzugriff: Detail-Ansicht
        followers = ticket.followers.all()
        attachments = Attachment.objects.filter(ticket=ticket)
        notifications = TicketEventService(ticket=ticket, current_user=user)
        new_problem_source = request.GET.get('problem_source')
        thanks = request.GET.get('thanks')

        if thanks:
            comment = Comment.objects.create(
                ticket=ticket,
                text=random.choice(thanks_comments),
            )
            notifications.create_comment_events(comment=comment, reopen=False)

        context = {
            "attachments": attachments,
            "search_user_form": SearchUsersForm(),
            "ticket": ticket,
            "followers": followers,
            "co_assignees": ticket.co_assignees.all(),
            "has_access": True,
            "can_manage": can_manage,
        }

        # Edit-Modus
        if 'edit' in request.get_full_path().split('/'):
            context['edit'] = True
            # Edit-Form nur sinnvoll, wenn managen erlaubt ist – das checkt später das Teiltemplate
            context['ticket_form'] = CreateTicketForm(initial={'note': ticket.note})

        # Verwaltungs-Elemente NUR für Hauptbearbeiter bereitstellen
        if can_manage:
            context['employees'] = User.objects.filter(is_staff=True)
            context['problem_sources'] = ProblemSource.objects.all()
            context['pause_ticket_form'] = PauseTicketForm()
            context['all_teams'] = Team.objects.all().order_by('name')

            if new_problem_source:
                ticket.problem_source_id = new_problem_source
                ticket.save()

        notifications.mark_events_as_seen()
        context["timeline_events"] = notifications.get_unique_events()

        if can_manage:
            context['employees_not_assigned'] = User.objects.filter(is_staff=True).exclude(
                pk__in=ticket.co_assignees.values('pk')
            ).exclude(pk=ticket.assigned_to_id)

        return render(
            request=request,
            template_name='ticket/ticket_detail.html',
            context=context
        )

    # ----- POST -----
    def post(self, request, *args, **kwargs):
        ticket = self.get_ticket()
        user = request.user

        has_access = self.user_has_full_access(user, ticket)
        can_manage = self.user_can_manage(user, ticket)

        # Wenn nicht mal Details erlaubt: nur Hinweis, nichts ändern
        if not has_access:
            return render(
                request=request,
                template_name='ticket/ticket_detail.html',
                context={
                    "ticket": ticket,
                    "has_access": False,
                    "can_manage": False,
                    "post_blocked": True,
                }
            )

        post = request.POST
        notifications = TicketEventService(ticket=ticket, current_user=user)

        # --- Aktionen für alle mit Zugriff (Kommentare/Antworten/Anhänge) ---
        new_comment = post.get('new_comment')
        new_comment_reply = post.get('new_reply')
        new_attachments = request.FILES.getlist('files')

        if new_comment:
            comment = Comment.objects.create(ticket=ticket, text=new_comment)
            notifications.create_comment_events(comment=comment)

        if new_comment_reply:
            comment_id = post.get('comment_id')
            reply = Comment.objects.create(
                ticket=ticket,
                text=new_comment_reply,
                parent=Comment.objects.get(id=comment_id)
            )
            notifications.create_reply_events(reply=reply)

        if new_attachments:
            for attachment in new_attachments:
                Attachment.objects.create(name=attachment, file=attachment, ticket=ticket)
            notifications.create_attachment_events()

        # --- Verwaltungsaktionen NUR für Hauptbearbeiter ---
        if can_manage:
            internal_note = post.get('internal_note')
            new_note = post.get('note')
            title = post.get('title')
            close = post.get('close')
            open_ = post.get('open')
            assign_to = post.get('assign_to')
            assign_team = post.get('assign_team')
            priority = post.get('priority')
            pause_until = post.get('pause_until')
            unpause = post.get('unpause')
            add_co = post.get('add_co_assignee')
            remove_co = post.get('remove_co_assignee')

            # Notiz / Titel
            if new_note is not None and ticket.note != new_note:
                ticket.note = new_note
                ticket.save()
                notifications.create_edit_events()

            if title and title != ticket.title:
                ticket.title = title
                ticket.save()

            # Schließen / Öffnen
            if close and not ticket.completed:
                close_comment = Comment.objects.create(ticket=ticket, text=internal_note) if internal_note else None
                ticket.completed = True
                ticket.save()
                notifications.create_close_events(comment=close_comment)

            if open_ and ticket.completed:
                ticket.completed = False
                ticket.save()
                notifications.create_open_events()

            # Nutzer zuweisen
            if assign_to:
                user_to_assign = User.objects.get(id=assign_to)
                followers = ticket.followers.all()
                followers_to_remove = [f for f in followers if f.is_staff]
                ticket.followers.remove(*followers_to_remove)
                ticket.followers.add(user_to_assign)
                ticket.co_assignees.add(user_to_assign)

                if ticket.assigned_to_id != user_to_assign.id:
                    comment = Comment.objects.create(ticket=ticket, text=internal_note) if internal_note else None
                    ticket.assigned_to = user_to_assign
                    ticket.save()
                    notifications.create_assign_events(comment=comment)

            # Team zuweisen / entfernen
            if assign_team is not None:
                if not assign_team or assign_team in ('null', 'None'):
                    if ticket.assigned_team_id is not None:
                        ticket.assigned_team = None
                        ticket.save()
                        if hasattr(notifications, "create_team_unassign_event"):
                            notifications.create_team_unassign_event()
                        else:
                            notifications.create_team_unassigned_event()
                else:
                    try:
                        team = Team.objects.get(pk=assign_team)
                    except Team.DoesNotExist:
                        team = None

                    if team and ticket.assigned_team_id != team.id:
                        ticket.assigned_team = team
                        ticket.save()
                        notifications.create_team_assigned_event(team)

            # Co-Assignees
            if add_co:
                try:
                    u = User.objects.get(pk=add_co)
                    ticket.co_assignees.add(u)
                    ticket.save()
                    notifications.create_co_assignee_added_event(u)
                except User.DoesNotExist:
                    pass

            if remove_co:
                try:
                    u = User.objects.get(pk=remove_co)
                    ticket.co_assignees.remove(u)
                    ticket.save()
                    notifications.create_co_assignee_removed_event(u)
                except User.DoesNotExist:
                    pass

            # Prio / Pausieren
            if priority is not None:
                ticket.priority = priority
                ticket.save()

            if pause_until:
                ticket.paused_until = pause_until
                ticket.save()

            if unpause:
                ticket.paused_until = None
                ticket.save()

            manual_update_analytics()

        return redirect("ticket_detail", id=ticket.id)

    # ----- Helpers -----
    def count_open_tickets_with_same_problem_source(self):
        ticket = self.get_ticket()
        return Ticket.objects.filter(problem_source=ticket.problem_source, completed=False).exclude(
            id=ticket.id
        ).count()

    def get_ticket(self):
        return get_object_or_404(
            Ticket.objects.select_related(
                "created_by", "assigned_to", "modified_by", "problem_source", "assigned_team",
            ).prefetch_related("co_assignees"),
            id=self.kwargs.get("id")
        )
