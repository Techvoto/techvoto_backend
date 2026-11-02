from django.urls import path

from . import views

urlpatterns = [
    path('checkout/', views.CheckoutView.as_view()),
    path('verify/<str:reference>/', views.VerifyPaymentView.as_view()),
    path('mine/', views.MyPaymentsView.as_view()),
    path('all/', views.AdminPaymentsView.as_view()),
    path('<int:pk>/request-refund/', views.RequestRefundView.as_view()),
    path('<int:pk>/refund/', views.AdminDirectRefundView.as_view()),
    path('refund-requests/', views.AdminRefundRequestList.as_view()),
    path('refund-requests/<int:pk>/approve/', views.AdminRefundRequestApprove.as_view()),
    path('refund-requests/<int:pk>/reject/', views.AdminRefundRequestReject.as_view()),
    path('webhook/', views.paystack_webhook),
]
