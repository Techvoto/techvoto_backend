from django.conf import settings
from django.db import models



class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'
        REFUND_PENDING = 'refund_pending', 'Refund pending'   # NEW
        REFUNDED = 'refunded', 'Refunded'                     # settlement confirmed
        REFUND_FAILED = 'refund_failed', 'Refund failed'      # NEW

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='payments')
    course = models.ForeignKey('courses.Course', on_delete=models.PROTECT, related_name='payments')
    reference = models.CharField(max_length=64, unique=True)
    amount_kobo = models.PositiveIntegerField()          # snapshot of the price at checkout time
    currency = models.CharField(max_length=3, default='NGN')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    gateway_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)
    refund_status = models.CharField(
    max_length=20, blank=True,
    help_text='Paystack refund lifecycle: initiating, pending, processed, failed',
)
    class Meta:
        ordering = ['-created_at']



    def __str__(self):
        return f'{self.reference} ({self.status})'


class RefundRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'   # NEW
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        FAILED = 'failed', 'Failed'               # NEW

    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name='refund_request')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='refund_requests')
    reason = models.TextField(max_length=2000)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    admin_note = models.TextField(blank=True, max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
