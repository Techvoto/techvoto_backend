from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('admin/users', views.AdminUserViewSet, basename='admin-users')

urlpatterns = [
    path('csrf/', views.CsrfCookieView.as_view()),
    path('register/', views.RegisterView.as_view()),
    path('login/', views.LoginView.as_view()),
    path('logout/', views.LogoutView.as_view()),
    path('token/refresh/', views.CookieTokenRefreshView.as_view()),
    path('me/', views.MeView.as_view()),
    path('change-password/', views.ChangePasswordView.as_view()),
    path('verify-email/', views.VerifyEmailView.as_view()),
    path('resend-verification/', views.ResendVerificationView.as_view()),
    path('password-reset/', views.PasswordResetRequestView.as_view()),
    path('password-reset/confirm/', views.PasswordResetConfirmView.as_view()),
    path('', include(router.urls)),
]
