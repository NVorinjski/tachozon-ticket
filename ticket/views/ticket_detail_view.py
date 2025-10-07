import random

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template import loader
from django.views import View

from ticket.forms import SearchUsersForm, CreateTicketForm, PauseTicketForm
from ticket.models import Attachment, Ticket, Comment, ProblemSource
from ticket.services import TicketEventService
from ticket.tasks import manual_update_analytics
from ticket.thanks import thanks_comments

from authentication.models import Team


class TicketDetailView(View):
    def get(self, request, *args, **kwargs):
        ticket = self.get_ticket()
        user = request.user
        followers = ticket.followers.all()

        if user in followers or user == ticket.created_by or user.is_staff:
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
            }



            # Edit-Modus
            if 'edit' in request.get_full_path().split('/'):
                context['edit'] = True
                context['ticket_form'] = CreateTicketForm(initial={'note': ticket.note})

            if user.is_staff:
                context['employees'] = User.objects.filter(is_staff=True)
                context['problem_sources'] = ProblemSource.objects.all()
                context['pause_ticket_form'] = PauseTicketForm()

                # Alle Teams für das Actions-Dropdown bereitstellen
                context['all_teams'] = Team.objects.all().order_by('name')

                if new_problem_source:
                    ticket.problem_source_id = new_problem_source
                    ticket.save()

                # Auto-Zuweisung an aktuellen Staff-User, falls noch niemand zugewiesen ist
                if not ticket.assigned_to:
                    followers_to_remove = [f for f in followers if f.is_staff and f != user]
                    ticket.followers.remove(*followers_to_remove)
                    ticket.assigned_to = user
                    ticket.save()
                    notifications.create_assign_events(is_automatic=True)

            notifications.mark_events_as_seen()
            context["timeline_events"] = notifications.get_unique_events()
            context["ticket"] = ticket
            context["followers"] = followers
            context['co_assignees'] = ticket.co_assignees.all()
            # Mitarbeiter, die noch NICHT co_assignee sind (für „hinzufügen“-Liste):
            context['employees_not_assigned'] = User.objects.filter(is_staff=True).exclude(
                pk__in=ticket.co_assignees.values('pk')
            ).exclude(pk=ticket.assigned_to_id)

            return render(
                request=request,
                template_name='ticket/ticket_detail.html',
                context=context
            )

        # keine Berechtigung
        html_template = loader.get_template('403.html')
        return HttpResponse(html_template.render({}, request))

    def post(self, request, *args, **kwargs):
        ticket = self.get_ticket()
        current_user = request.user
        post = request.POST

        notifications = TicketEventService(ticket=ticket, current_user=current_user)

        # POST-Daten
        new_comment = post.get('new_comment')
        internal_note = post.get('internal_note')
        new_note = post.get('note')
        new_attachments = request.FILES.getlist('files')
        new_comment_reply = post.get('new_reply')
        close = post.get('close')
        open_ = post.get('open')  # Built-in nicht überschreiben
        title = post.get('title')
        assign_to = post.get('assign_to')
        assign_team = post.get('assign_team')  # <-- Team-Zuweisung
        priority = post.get('priority')
        pause_until = post.get('pause_until')
        unpause = post.get('unpause')
        add_co = post.get('add_co_assignee')
        remove_co = post.get('remove_co_assignee')

        # Kommentare
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

        # Notiz / Titel
        if new_note and ticket.note != new_note:
            ticket.note = new_note
            ticket.save()
            notifications.create_edit_events()

        if title and title != ticket.title:
            ticket.title = title
            ticket.save()

        # Attachments
        if new_attachments:
            for attachment in new_attachments:
                Attachment.objects.create(
                    name=attachment,
                    file=attachment,
                    ticket=ticket
                )
            notifications.create_attachment_events()

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
        # Wird durch Buttons im Actions-Dropdown ausgelöst (name="assign_team")
        if assign_team is not None and current_user.is_staff:
            # leeren erlaubt: '', 'null', 'None' -> Team entfernen
            if not assign_team or assign_team in ('null', 'None'):
                if ticket.assigned_team_id is not None:
                    ticket.assigned_team = None
                    ticket.save()
                    notifications.create_edit_events()
            else:
                try:
                    team = Team.objects.get(pk=assign_team)
                except Team.DoesNotExist:
                    team = None

                if team and ticket.assigned_team_id != team.id:
                    # Optional-Policy: sicherstellen, dass Assignee Mitglied des Teams ist
                    # if ticket.assigned_to and not team.members.filter(pk=ticket.assigned_to_id).exists():
                    #     pass  # hier abbrechen / Meldung setzen, falls erzwingen gewünscht
                    ticket.assigned_team = team
                    ticket.save()
                    notifications.create_edit_events()

        if add_co and current_user.is_staff:
            try:
                u = User.objects.get(pk=add_co)
                ticket.co_assignees.add(u)
                ticket.save()
                # (optional) notifications.create_assign_events(...) o. ä.
            except User.DoesNotExist:
                pass

        if remove_co and current_user.is_staff:
            try:
                u = User.objects.get(pk=remove_co)
                ticket.co_assignees.remove(u)
                ticket.save()
            except User.DoesNotExist:
                pass

        # Prio / Pausieren
        if priority:
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

    def count_open_tickets_with_same_problem_source(self):
        ticket = self.get_ticket()
        return Ticket.objects.filter(problem_source=ticket.problem_source, completed=False).exclude(
            id=ticket.id).count()

    def get_ticket(self):
        return get_object_or_404(
            Ticket.objects.select_related(
                "created_by",
                "assigned_to",
                "modified_by",
                "problem_source",
                "assigned_team",
            ).prefetch_related("co_assignees"),
            id=self.kwargs.get("id")
        )
