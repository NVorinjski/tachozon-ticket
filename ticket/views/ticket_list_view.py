from urllib.parse import urlencode

from django.db.models import Q
from django.views.generic import ListView

from ticket.models import Ticket


class TicketListView(ListView):
    model = Ticket
    template_name = 'ticket/ticket_list.html'
    context_object_name = "tickets"
    paginate_by = 25

    default_ordering = ('completed', '-priority', '-created_date')
    sortable_fields = {
        'id': ('id',),
        'problem_source': ('problem_source__breadcrumb',),
        'created_date': ('created_date',),
        'created_by': ('created_by__first_name', 'created_by__last_name'),
        'last_modified': ('last_modified',),
        'modified_by': ('modified_by__first_name', 'modified_by__last_name'),
        'assigned_to': ('assigned_to__first_name', 'assigned_to__last_name'),
        'completed': ('completed',),
        'priority': ('priority',),
    }

    def get_base_queryset(self):
        status = self.kwargs.get('status')
        ticket_type = self.kwargs.get('type')
        user = self.request.user

        if ticket_type == "mine":
            if status == "open":
                tickets = Ticket.objects.open_and_created_by(user)
            elif status == "closed":
                tickets = Ticket.objects.closed_and_created_by(user)
            else:
                tickets = Ticket.objects.created_by(user)
        elif ticket_type == "assigned_to_me":
            base = Ticket.objects.filter(
                Q(assigned_to=user) |
                Q(co_assignees=user) |
                Q(assigned_team__members=user)
            ).distinct().select_related(
                'created_by', 'assigned_to', 'modified_by', 'problem_source', 'assigned_team'
            ).prefetch_related('co_assignees')

            if status == "open":
                tickets = base.filter(completed=False)
            elif status == "closed":
                tickets = base.filter(completed=True)
            else:
                tickets = base
        elif ticket_type == "all" and user.is_staff:
            if status == "open":
                tickets = Ticket.objects.all_open()
            elif status == "closed":
                tickets = Ticket.objects.all_closed()
            else:
                tickets = Ticket.objects.all().select_related(
                    'created_by', 'assigned_to', 'modified_by', 'problem_source'
                )
        else:
            tickets = Ticket.objects.none()

        return tickets

    def get_sorting(self):
        sort = self.request.GET.get('sort')
        direction = self.request.GET.get('dir')

        if sort not in self.sortable_fields or direction not in {'asc', 'desc'}:
            return None, None, self.default_ordering

        prefix = '-' if direction == 'desc' else ''
        ordering = tuple(f'{prefix}{field}' for field in self.sortable_fields[sort])
        return sort, direction, ordering

    def get_queryset(self):
        tickets = self.get_base_queryset()
        _, _, ordering = self.get_sorting()
        return tickets.order_by(*ordering)

    def build_query_string(self, **kwargs):
        params = self.request.GET.copy()

        for key, value in kwargs.items():
            if value in [None, '']:
                params.pop(key, None)
            else:
                params[key] = value

        if 'page' not in kwargs:
            params.pop('page', None)

        encoded = urlencode(params, doseq=True)
        return f'?{encoded}' if encoded else ''

    def get_sort_link(self, field_name):
        current_sort, current_direction, _ = self.get_sorting()

        if current_sort != field_name:
            return self.build_query_string(sort=field_name, dir='desc')

        if current_direction == 'desc':
            return self.build_query_string(sort=field_name, dir='asc')

        return self.build_query_string(sort=None, dir=None)

    def get_sort_icon(self, field_name):
        current_sort, current_direction, _ = self.get_sorting()

        if current_sort != field_name:
            return 'fas fa-sort text-muted'

        if current_direction == 'desc':
            return 'fas fa-sort-down'

        return 'fas fa-sort-up'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_sort, current_direction, _ = self.get_sorting()

        context['ticket_status'] = self.kwargs.get('status')
        context['ticket_type'] = self.kwargs.get('type')
        context['current_sort'] = current_sort
        context['current_sort_direction'] = current_direction
        context['sort_links'] = {
            field_name: self.get_sort_link(field_name)
            for field_name in self.sortable_fields
        }
        context['sort_icons'] = {
            field_name: self.get_sort_icon(field_name)
            for field_name in self.sortable_fields
        }
        context['pagination_query'] = self.build_query_string()
        return context
