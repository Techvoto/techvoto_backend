from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .models import User


class UserCreateForm(UserCreationForm):
    # Django's default form expects a `username` field; this project logs in by email.
    class Meta:
        model = User
        fields = ('email', 'first_name', 'last_name', 'role')


class UserEditForm(UserChangeForm):
    class Meta:
        model = User
        fields = '__all__'


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserEditForm
    add_form = UserCreateForm
    list_display = ['email', 'first_name', 'last_name', 'role', 'email_verified', 'xp', 'streak', 'is_active', 'date_joined']
    search_fields = ['email', 'first_name', 'last_name']
    list_filter = ['role', 'is_active', 'is_staff']
    ordering = ['-date_joined']
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal', {'fields': ('first_name', 'last_name', 'avatar', 'bio')}),
        ('Learning', {'fields': ('role', 'email_verified', 'xp', 'streak', 'last_streak_date')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
    )
    add_fieldsets = ((None, {'classes': ('wide',), 'fields': (
        'email', 'first_name', 'last_name', 'role', 'password1', 'password2')}),)
