import logging
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def safe_send_mail(subject, message, recipients):
    """Queue mail for Celery; fall back to synchronous SMTP if the broker is unavailable."""
    recipients = list(recipients or [])
    if not recipients:
        return 0
    try:
        from apps.core.tasks import send_email_task
        send_email_task.delay(subject, message, recipients)
        return 1  # accepted by the broker, not a claim of final SMTP delivery
    except Exception:
        logger.exception('Could not queue email %r; attempting synchronous fallback', subject)
        try:
            return send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=False)
        except Exception:
            logger.exception('Synchronous email fallback failed for %r', subject)
            return 0
