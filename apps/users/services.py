from django.conf import settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.core.mail import safe_send_mail
from .tokens import email_verification_token


def send_verification_email(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    link = f'{settings.FRONTEND_URL}/verify-email?uid={uid}&token={token}'
    safe_send_mail('Verify your Techvoto email',
                   f'Hi {user.first_name},\n\nWelcome to Techvoto! Confirm your email address to start enrolling in courses:\n{link}\n\n'
                   'If you did not create this account, you can ignore this email.',
                   [user.email])
