import hashlib
import hmac

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.courses.models import Certificate, Enrollment
from apps.courses.services import enroll_user, notify
from .models import Payment


class PaystackError(Exception):
    pass


def _headers():
    return {'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}', 'Content-Type': 'application/json'}


def initialize(payment, callback_url):
    try:
        r = requests.post(f'{settings.PAYSTACK_BASE_URL}/transaction/initialize', headers=_headers(), timeout=15, json={
            'email': payment.user.email, 'amount': payment.amount_kobo, 'currency': payment.currency,
            'reference': payment.reference, 'callback_url': callback_url,
            'metadata': {'course_id': payment.course_id, 'user_id': payment.user_id}})
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaystackError('Could not reach the payment provider.') from exc
    if not data.get('status'):
        raise PaystackError(data.get('message', 'Payment provider rejected the request.'))
    return data['data']['authorization_url']


def verify(reference):
    try:
        r = requests.get(f'{settings.PAYSTACK_BASE_URL}/transaction/verify/{reference}', headers=_headers(), timeout=15)
        r.raise_for_status()
        return r.json()['data']
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise PaystackError('Could not verify the payment right now.') from exc


@transaction.atomic
def fulfil(reference, gateway_data):
    """Idempotent. The webhook and the browser-return verify may both call this for the same payment."""
    payment = Payment.objects.select_for_update().select_related('user', 'course').filter(reference=reference).first()
    if payment is None:
        return None
    if payment.status == Payment.Status.SUCCESS:
        return payment
    try:
        gateway_amount = int(gateway_data.get('amount', -1))
    except (TypeError, ValueError):
        gateway_amount = -1
    paid_ok = (gateway_data.get('status') == 'success'
               and gateway_amount == payment.amount_kobo      # never trust the client; compare to our snapshot
               and gateway_data.get('currency', payment.currency) == payment.currency)
    payment.gateway_response = {k: gateway_data.get(k) for k in ('id', 'status', 'amount', 'currency', 'channel', 'paid_at')}
    if paid_ok:
        payment.status, payment.paid_at = Payment.Status.SUCCESS, timezone.now()
        payment.save()
        enroll_user(payment.user, payment.course, Enrollment.Source.PAID)
    elif gateway_data.get('status') in ('failed', 'abandoned', 'reversed'):
        payment.status = Payment.Status.FAILED
        payment.save()
    else:
        payment.save(update_fields=['gateway_response'])
    return payment


def valid_signature(raw_body: bytes, header: str) -> bool:
    if not settings.PAYSTACK_SECRET_KEY or not header:
        return False
    expected = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, header)


def refund_eligibility(payment):
    """Returns (ok, reason). Policy comes from REFUND_WINDOW_DAYS and REFUND_MAX_PROGRESS."""
    from datetime import timedelta
    if payment.status != Payment.Status.SUCCESS:
        return False, 'Only successful payments can be refunded.'
    if hasattr(payment, 'refund_request'):
        return False, 'A refund has already been requested for this payment.'
    if payment.paid_at and timezone.now() > payment.paid_at + timedelta(days=settings.REFUND_WINDOW_DAYS):
        return False, f'The {settings.REFUND_WINDOW_DAYS}-day refund window has passed.'
    e = Enrollment.objects.filter(user=payment.user, course=payment.course).first()
    if e and e.progress_pct > settings.REFUND_MAX_PROGRESS:
        return False, f'Refunds are only available before you complete {settings.REFUND_MAX_PROGRESS}% of the course.'
    return True, ''


def paystack_refund(reference):
    try:
        r = requests.post(f'{settings.PAYSTACK_BASE_URL}/refund', headers=_headers(), timeout=20,
                          json={'transaction': reference})
        data = r.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaystackError('Could not reach the payment provider.') from exc
    if not r.ok or not data.get('status'):
        raise PaystackError(data.get('message', 'Paystack rejected the refund.'))
    return data.get('data') or {}


def refund_payment(payment):
    """Initiate a refund. Two-phase: (1) reserve the row, call Paystack,
    (2) record the initiation result. Access is revoked only on 'processed'."""
    # Phase 1 — short lock, mark as pending, no HTTP call yet.
    with transaction.atomic():
        locked = (
            Payment.objects.select_for_update()
            .select_related('user', 'course')
            .get(pk=payment.pk)
        )
        if locked.status == Payment.Status.REFUNDED:
            return locked                     # already settled — idempotent
        if locked.status == Payment.Status.REFUND_PENDING:
            raise PaystackError('A refund for this payment is already in progress.')
        if locked.status != Payment.Status.SUCCESS:
            raise PaystackError('Only successful payments can be refunded.')
        locked.status = Payment.Status.REFUND_PENDING
        locked.refund_status = 'initiating'
        locked.save(update_fields=['status', 'refund_status'])
        reference = locked.reference

    # Phase 2 — call the gateway OUTSIDE the lock. No DB connection held.
    try:
        data = paystack_refund(reference)
    except PaystackError:
        # Gateway unreachable: revert the reservation, no state change.
        Payment.objects.filter(pk=payment.pk, status=Payment.Status.REFUND_PENDING).update(
            status=Payment.Status.SUCCESS, refund_status='',
        )
        raise

    # Phase 3 — record what Paystack told us. Never mark REFUNDED here.
    gateway_status = str(data.get('status', 'pending')).lower()
    Payment.objects.filter(pk=payment.pk).update(
        refund_status=gateway_status[:20],
    )
    # If Paystack says the refund was rejected synchronously, revert.
    if gateway_status in ('failed', 'reversed'):
        Payment.objects.filter(pk=payment.pk).update(
            status=Payment.Status.REFUND_FAILED, refund_status=gateway_status[:20],
        )
        raise PaystackError('Paystack rejected the refund.')

    payment.refresh_from_db()
    notify(payment.user, f'Refund initiated: {payment.course.title}',
           'Your refund has been submitted to Paystack. Access will be updated when the bank confirms.',
           '/billing')
    return payment


def handle_refund_event(event, data):
    """Paystack settlement webhook. Revokes access only on `processed`;
    restores it on `failed` if it was previously revoked."""
    reference = data.get('transaction_reference', '')
    if not reference:
        return

    with transaction.atomic():
        payment = (
            Payment.objects.select_for_update()
            .select_related('user', 'course')
            .filter(reference=reference).first()
        )
        if not payment:
            return

        if event == 'refund.processed':
            if payment.status == Payment.Status.REFUNDED:
                return                                   # idempotent
            payment.status = Payment.Status.REFUNDED
            payment.refunded_at = timezone.now()
            payment.refund_status = 'processed'
            payment.save(update_fields=['status', 'refunded_at', 'refund_status'])
            Enrollment.objects.filter(
                user=payment.user, course=payment.course,
                source=Enrollment.Source.PAID,
            ).delete()
            Certificate.objects.filter(user=payment.user, course=payment.course).delete()
            _notify_user = (payment.user, payment.course)

        elif event == 'refund.failed':
            if payment.status == Payment.Status.REFUNDED:
                # Access was revoked but the refund then failed — restore it.
                Enrollment.objects.get_or_create(
                    user=payment.user, course=payment.course,
                    defaults={'source': Enrollment.Source.PAID},
                )
            payment.status = Payment.Status.REFUND_FAILED
            payment.refund_status = 'failed'
            payment.save(update_fields=['status', 'refund_status'])
            from apps.users.models import User
            for admin in User.objects.filter(role='admin', is_active=True):
                notify(admin, 'Refund failed at Paystack',
                       f'Payment {payment.reference} needs manual attention.', '/admin/payments')
            _notify_user = None

        else:
            return

    if _notify_user:
        user, course = _notify_user
        notify(user, f'Refund processed: {course.title}',
               'Your refund has been processed by your bank.', '/billing')