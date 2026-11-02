from django.core.management.base import BaseCommand

from apps.users.models import User


class Command(BaseCommand):
    help = 'Mark existing users as email-verified (use once after adding email verification to a live database)'

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true', help='Mark every user as verified')
        parser.add_argument('emails', nargs='*', help='Specific emails to mark as verified')

    def handle(self, *args, **opts):
        qs = User.objects.all() if opts['all'] else User.objects.filter(email__in=opts['emails'])
        n = qs.update(email_verified=True)
        self.stdout.write(self.style.SUCCESS(f'{n} user(s) marked as verified.'))
