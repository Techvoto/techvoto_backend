from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Unlike the password-reset token, this one is not invalidated by logging in (last_login is not in the hash)."""
    key_salt = 'apps.users.EmailVerificationTokenGenerator'

    def _make_hash_value(self, user, timestamp):
        return f'{user.pk}{user.email}{user.email_verified}{timestamp}'


email_verification_token = EmailVerificationTokenGenerator()
