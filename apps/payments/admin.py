from django.contrib import admin

from .models import Payment, RefundRequest


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['reference', 'user', 'course', 'amount_kobo', 'status', 'created_at']
    list_filter = ['status']
    readonly_fields = [f.name for f in Payment._meta.fields]


admin.site.register(RefundRequest)
