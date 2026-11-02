import hashlib
import hmac
import json
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.core.testing import make_course, make_user
from apps.courses.models import Enrollment
from .models import Payment

SECRET = 'sk_test_secret'


def signed_post(client, payload, secret=SECRET):
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    return client.post('/api/payments/webhook/', data=body, content_type='application/json',
                       HTTP_X_PAYSTACK_SIGNATURE=sig)


@override_settings(PAYSTACK_SECRET_KEY=SECRET)
class PaymentTests(TestCase):
    def setUp(self):
        self.teacher, self.student = make_user('t@x.com', 'instructor'), make_user('s@x.com')
        self.course, _ = make_course(self.teacher, price_kobo=500000)
        self.payment = Payment.objects.create(user=self.student, course=self.course, reference='tv_abc',
                                              amount_kobo=500000)
        self.c = APIClient()

    def event(self, amount=500000, status='success'):
        return {'event': 'charge.success', 'data': {'reference': 'tv_abc', 'status': status,
                                                    'amount': amount, 'currency': 'NGN'}}

    def test_bad_signature_rejected(self):
        r = signed_post(self.c, self.event(), secret='wrong')
        self.assertEqual(r.status_code, 401)
        self.assertFalse(Enrollment.objects.exists())

    def test_valid_webhook_enrolls_once(self):
        self.assertEqual(signed_post(self.c, self.event()).status_code, 200)
        self.assertEqual(signed_post(self.c, self.event()).status_code, 200)   # replay
        self.assertEqual(Enrollment.objects.filter(user=self.student, course=self.course).count(), 1)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'success')

    def test_underpayment_does_not_enroll(self):
        signed_post(self.c, self.event(amount=100))
        self.assertFalse(Enrollment.objects.exists())

    def test_checkout_uses_server_side_price(self):
        self.c.force_authenticate(self.student)
        with mock.patch('apps.payments.services.initialize', return_value='https://paystack.test/pay'):
            r = self.c.post('/api/payments/checkout/', {'course_slug': self.course.slug, 'amount': 1}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        newest = Payment.objects.latest('id')
        self.assertEqual(newest.amount_kobo, 500000)

    def test_cannot_verify_someone_elses_payment(self):
        self.c.force_authenticate(make_user('other@x.com'))
        self.assertEqual(self.c.get('/api/payments/verify/tv_abc/').status_code, 404)


@override_settings(PAYSTACK_SECRET_KEY=SECRET)
class RefundTests(TestCase):
    def setUp(self):
        from django.utils import timezone
        self.teacher, self.student = make_user('t@x.com', 'instructor'), make_user('s@x.com')
        self.admin = make_user('a@x.com', 'admin')
        self.course, _ = make_course(self.teacher, price_kobo=500000)
        self.payment = Payment.objects.create(user=self.student, course=self.course, reference='tv_r1', amount_kobo=500000,
                                              status='success', paid_at=timezone.now())
        self.enrollment = Enrollment.objects.create(user=self.student, course=self.course, source='paid')
        self.c = APIClient()

    def request_refund(self, reason='The course was not what I expected.'):
        self.c.force_authenticate(self.student)
        return self.c.post(f'/api/payments/{self.payment.id}/request-refund/', {'reason': reason}, format='json')

    def test_student_can_request_once(self):
        self.assertEqual(self.request_refund().status_code, 201)
        self.assertEqual(self.request_refund().status_code, 400)

    def test_short_reason_rejected(self):
        self.assertEqual(self.request_refund('no').status_code, 400)

    def test_cannot_request_for_someone_elses_payment(self):
        self.c.force_authenticate(make_user('o@x.com'))
        r = self.c.post(f'/api/payments/{self.payment.id}/request-refund/', {'reason': 'a long enough reason'}, format='json')
        self.assertEqual(r.status_code, 404)

    def test_window_and_progress_limits(self):
        from datetime import timedelta
        from django.utils import timezone
        Payment.objects.filter(pk=self.payment.pk).update(paid_at=timezone.now() - timedelta(days=30))
        self.assertEqual(self.request_refund().status_code, 400)
        Payment.objects.filter(pk=self.payment.pk).update(paid_at=timezone.now())
        Enrollment.objects.filter(pk=self.enrollment.pk).update(progress_pct=80)
        self.assertEqual(self.request_refund().status_code, 400)

    # apps/payments/tests.py

    def test_admin_approval_initiates_refund_and_revokes_on_settlement(self):
        self.request_refund()
        req_id = self.payment.refund_request.id
        self.c.force_authenticate(self.admin)
        with mock.patch('apps.payments.services.paystack_refund',
                        return_value={'status': 'pending'}) as m:
            r = self.c.post(f'/api/payments/refund-requests/{req_id}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        m.assert_called_once_with('tv_r1')

        # Phase 1+3: pending, still enrolled, request approved
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'refund_pending')
        self.assertEqual(self.payment.refund_status, 'pending')
        self.assertTrue(Enrollment.objects.filter(user=self.student, course=self.course).exists())
        self.payment.refund_request.refresh_from_db()
        self.assertEqual(self.payment.refund_request.status, 'approved')

        # Webhook settles → access revoked
        from apps.payments.services import handle_refund_event
        handle_refund_event('refund.processed',
                            {'transaction_reference': 'tv_r1', 'status': 'processed'})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'refunded')
        self.assertFalse(Enrollment.objects.filter(user=self.student, course=self.course).exists())

    def test_approve_is_idempotent_under_retry(self):
        self.request_refund()
        req_id = self.payment.refund_request.id
        self.c.force_authenticate(self.admin)
        with mock.patch('apps.payments.services.paystack_refund',
                        return_value={'status': 'pending'}) as m:
            first = self.c.post(f'/api/payments/refund-requests/{req_id}/approve/', {}, format='json')
            second = self.c.post(f'/api/payments/refund-requests/{req_id}/approve/', {}, format='json')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)   # idempotent
        m.assert_called_once_with('tv_r1')
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'refund_pending')

    def test_gateway_failure_changes_nothing(self):
        self.request_refund()
        req_id = self.payment.refund_request.id
        self.c.force_authenticate(self.admin)
        from apps.payments.services import PaystackError
        with mock.patch('apps.payments.services.paystack_refund', side_effect=PaystackError('down')):
            r = self.c.post(f'/api/payments/refund-requests/{req_id}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 502)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'success')
        self.assertTrue(Enrollment.objects.filter(user=self.student, course=self.course).exists())

    def test_student_cannot_approve_own_request(self):
        self.request_refund()
        r = self.c.post(f'/api/payments/refund-requests/{self.payment.refund_request.id}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_rejection_keeps_access(self):
        self.request_refund()
        self.c.force_authenticate(self.admin)
        r = self.c.post(f'/api/payments/refund-requests/{self.payment.refund_request.id}/reject/', {'note': 'Outside policy'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Enrollment.objects.filter(user=self.student, course=self.course).exists())





from django.db import connection
from django.test import TransactionTestCase, skipUnlessDBFeature


@skipUnlessDBFeature('has_select_for_update')   # skips on SQLite
class RefundConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        from django.utils import timezone
        from apps.core.testing import make_course, make_user
        from apps.courses.models import Enrollment
        from apps.payments.models import Payment
        self.teacher = make_user('t@x.com', 'instructor')
        self.student = make_user('s@x.com')
        self.admin = make_user('a@x.com', 'admin')
        self.course, _ = make_course(self.teacher, price_kobo=500000)
        self.payment = Payment.objects.create(
            user=self.student, course=self.course, reference='tv_r1',
            amount_kobo=500000, status='success', paid_at=timezone.now())
        Enrollment.objects.create(
            user=self.student, course=self.course, source='paid')

    def test_concurrent_approve_does_not_double_refund(self):
        from concurrent.futures import ThreadPoolExecutor
        from rest_framework.test import APIClient
        from apps.payments.models import RefundRequest
        from django.db import connections
        from unittest import mock

        req = RefundRequest.objects.create(
            payment=self.payment, user=self.student,
            reason='I enrolled by mistake, need a refund please.')
        req_id = req.id

        with mock.patch(
            'apps.payments.services.paystack_refund',
            return_value={'status': 'pending'},
        ) as m:

            def hit(_):
                c = APIClient()
                c.force_authenticate(self.admin)
                try:
                    return c.post(
                        f'/api/payments/refund-requests/{req_id}/approve/',
                        {}, format='json',
                    ).status_code
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=4) as ex:
                codes = list(ex.map(hit, range(4)))

        self.assertTrue(all(c in (200, 409) for c in codes), codes)
        self.assertEqual(m.call_count, 1)   # gateway invoked exactly once
        self.payment.refresh_from_db()
        # Settlement pending — the webhook will flip it to REFUNDED.
        self.assertEqual(self.payment.status, 'refund_pending')