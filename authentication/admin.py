# Register your models here.
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from authentication.models import MicrosoftProfile, Team


class UserInline(admin.TabularInline):
    model = MicrosoftProfile

class UserAdmin(UserAdmin):
    inlines = [UserInline]


# unregister old user admin
admin.site.unregister(User)
# register new user admin
admin.site.register(User, UserAdmin)

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    filter_horizontal = ("members",)