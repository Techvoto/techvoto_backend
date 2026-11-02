from rest_framework import serializers

from .models import Payment, RefundRequest
from .services import refund_eligibility


class RefundRequestSerializer(serializers.ModelSerializer):
    student = serializers.CharField(source='user.full_name', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    course_title = serializers.CharField(source='payment.course.title', read_only=True)
    reference = serializers.CharField(source='payment.reference', read_only=True)
    amount_kobo = serializers.IntegerField(source='payment.amount_kobo', read_only=True)
    progress_pct = serializers.SerializerMethodField()

    class Meta:
        model = RefundRequest
        fields = ['id', 'payment', 'student', 'email', 'course_title', 'reference', 'amount_kobo', 'reason',
                  'status', 'admin_note', 'progress_pct', 'created_at', 'decided_at']
        read_only_fields = fields

    def get_progress_pct(self, obj):
        e = obj.payment.course.enrollments.filter(user=obj.user).first()
        return e.progress_pct if e else None


class PaymentSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source='course.title', read_only=True)
    course_slug = serializers.CharField(source='course.slug', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    can_request_refund = serializers.SerializerMethodField()
    refund_request_status = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = ['id', 'reference', 'course_title', 'course_slug', 'user_email', 'amount_kobo', 'currency',
                  'status', 'created_at', 'paid_at', 'refunded_at', 'refund_status', 'can_request_refund',
                  'refund_request_status']
        read_only_fields = fields

    def get_can_request_refund(self, obj):
        return refund_eligibility(obj)[0]

    def get_refund_request_status(self, obj):
        return obj.refund_request.status if hasattr(obj, 'refund_request') else None
