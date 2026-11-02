import logging
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

@shared_task(
    bind=True,
    ignore_result=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    name='core.send_email',
)
def send_email_task(self, subject, message, recipients):
    """Deliver transactional email outside the web request; retries transient SMTP errors."""
    recipients = list(recipients or [])
    if not recipients:
        return 0
    sent = send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=False)
    logger.info('Email delivery completed: subject=%r recipients=%d sent=%d', subject, len(recipients), sent)
    return sent


