import json
import uuid

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.permissions import IsAdminRole, require_verified
from apps.courses.models import Course, Enrollment
from . import services
from apps.courses.services import notify
from .models import Payment, RefundRequest
from .serializers import PaymentSerializer, RefundRequestSerializer
# apps/payments/views.py — header additions
from django.db import transaction          # ← ADD
from django.http import HttpResponse, HttpResponseRedirect
from rest_framework.exceptions import NotFound   # ← ADD (used in AdminRefundRequestApprove)

class CheckoutView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'checkout'

    def post(self, request):
        require_verified(request.user)
        if not settings.PAYSTACK_SECRET_KEY:
            return Response({'detail': 'Payments are not configured yet.'}, status=503)
        course = Course.objects.filter(slug=request.data.get('course_slug'), status=Course.Status.PUBLISHED).first()
        if not course:
            raise ValidationError({'course_slug': 'Course not found.'})
        if course.is_free:
            raise ValidationError('This course is free — enroll directly.')
        if course.instructor_id == request.user.id or \
                Enrollment.objects.filter(user=request.user, course=course).exists():
            raise ValidationError('You already have access to this course.')
        # Amount comes from the database, never from the request.
        payment = Payment.objects.create(user=request.user, course=course, amount_kobo=course.price_kobo,
                                         reference=f'tv_{uuid.uuid4().hex}')
        try:
            url = services.initialize(payment, f'{settings.FRONTEND_URL}/checkout/verify?reference={payment.reference}')
        except services.PaystackError as exc:
            payment.status = Payment.Status.FAILED
            payment.save(update_fields=['status'])
            return Response({'detail': str(exc)}, status=502)
        return Response({'authorization_url': url, 'reference': payment.reference}, status=201)


class VerifyPaymentView(APIView):
    """Called when the browser returns from Paystack. The webhook may already have fulfilled it."""

    def get(self, request, reference):
        payment = Payment.objects.filter(reference=reference, user=request.user).select_related('course').first()
        if not payment:
            return Response({'detail': 'Payment not found.'}, status=404)
        if payment.status == Payment.Status.PENDING:
            try:
                payment = services.fulfil(reference, services.verify(reference))
            except services.PaystackError as exc:
                return Response({'status': 'pending', 'detail': str(exc)}, status=202)
        return Response({'status': payment.status, 'course_slug': payment.course.slug})


class MyPaymentsView(generics.ListAPIView):
    serializer_class = PaymentSerializer

    def get_queryset(self):
        return Payment.objects.filter(user=self.request.user).select_related('course', 'user')


class AdminPaymentsView(generics.ListAPIView):
    serializer_class = PaymentSerializer
    permission_classes = [IsAdminRole]
    filterset_fields = ['status']
    queryset = Payment.objects.select_related('course', 'user')


@csrf_exempt
@require_POST
def paystack_webhook(request):
    """Server-to-server. Authenticated by the HMAC signature, not by a user session."""
    if not services.valid_signature(request.body, request.headers.get('x-paystack-signature', '')):
        return HttpResponse(status=401)
    try:
        event = json.loads(request.body)
    except ValueError:
        return HttpResponse(status=400)
    data = event.get('data') or {}
    if event.get('event') == 'charge.success':
        services.fulfil(data.get('reference', ''), data)
    elif event.get('event') in ('refund.processed', 'refund.failed'):
        services.handle_refund_event(event['event'], data)
    return HttpResponse(status=200)


class RequestRefundView(APIView):
    """Student asks for a refund. An admin approves or rejects it."""

    def post(self, request, pk):
        payment = get_object_or_404(Payment.objects.select_related('course', 'user'), pk=pk, user=request.user)
        ok, reason = services.refund_eligibility(payment)
        if not ok:
            raise ValidationError(reason)
        text = str(request.data.get('reason', '')).strip()
        if len(text) < 10:
            raise ValidationError({'reason': 'Please tell us a little about why you want a refund (at least 10 characters).'})
        req = RefundRequest.objects.create(payment=payment, user=request.user, reason=text[:2000])
        from apps.users.models import User
        for admin in User.objects.filter(role='admin', is_active=True):
            notify(admin, 'New refund request', f'{request.user.full_name} - {payment.course.title}', '/admin/refunds')
        return Response(RefundRequestSerializer(req).data, status=201)


class AdminRefundRequestList(generics.ListAPIView):
    serializer_class = RefundRequestSerializer
    permission_classes = [IsAdminRole]
    filterset_fields = ['status']
    queryset = RefundRequest.objects.select_related('payment__course', 'user')


class AdminRefundRequestApprove(APIView):
    permission_classes = [IsAdminRole]

    def post(self, request, pk):
        # Phase 1: claim the request atomically.
        with transaction.atomic():
            req = (
                RefundRequest.objects.select_for_update()
                .select_related('payment__user', 'payment__course')
                .filter(pk=pk).first()
            )
            if not req:
                raise NotFound()
            if req.status == RefundRequest.Status.APPROVED:
                return Response(RefundRequestSerializer(req).data)          # idempotent
            if req.status == RefundRequest.Status.PROCESSING:
                return Response({'detail': 'Refund already in progress.'}, status=409)
            if req.status != RefundRequest.Status.PENDING:
                raise ValidationError('This request has already been decided.')
            req.status = RefundRequest.Status.PROCESSING
            req.decided_by = request.user
            req.decided_at = timezone.now()
            req.admin_note = str(request.data.get('note', ''))[:1000]
            req.save(update_fields=['status', 'decided_by', 'decided_at', 'admin_note'])
            payment = req.payment

        # Phase 2: gateway call OUTSIDE the transaction.
        try:
            services.refund_payment(payment)
        except services.PaystackError as exc:
            with transaction.atomic():
                RefundRequest.objects.filter(
                    pk=pk, status=RefundRequest.Status.PROCESSING,
                ).update(status=RefundRequest.Status.FAILED)
            return Response({'detail': str(exc)}, status=502)

        # Phase 3: mark approved (settlement still pending webhook).
        with transaction.atomic():
            RefundRequest.objects.filter(
                pk=pk, status=RefundRequest.Status.PROCESSING,
            ).update(status=RefundRequest.Status.APPROVED)
            req.refresh_from_db()
        return Response(RefundRequestSerializer(req).data)


class AdminRefundRequestReject(APIView):
    permission_classes = [IsAdminRole]

    def post(self, request, pk):
        req = get_object_or_404(RefundRequest.objects.select_related('payment__course', 'user'), pk=pk)
        if req.status != RefundRequest.Status.PENDING:
            raise ValidationError('This request has already been decided.')
        req.status, req.decided_by, req.decided_at = RefundRequest.Status.REJECTED, request.user, timezone.now()
        req.admin_note = str(request.data.get('note', ''))[:1000]
        req.save()
        notify(req.user, f'Refund request declined: {req.payment.course.title}', req.admin_note or 'Contact support for details.', '/billing')
        return Response(RefundRequestSerializer(req).data)


class AdminDirectRefundView(APIView):
    """Admin refunds a payment without a student request (e.g. a duplicate charge)."""
    permission_classes = [IsAdminRole]

    def post(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        try:
            payment = services.refund_payment(payment)
        except services.PaystackError as exc:
            return Response({'detail': str(exc)}, status=502)
        return Response(PaymentSerializer(payment).data)
