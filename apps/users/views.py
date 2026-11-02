from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import generics, mixins, permissions, status, viewsets
from rest_framework.filters import SearchFilter
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from .cookies import set_auth_cookies, clear_auth_cookies

from apps.core.mail import safe_send_mail
from apps.core.permissions import IsAdminRole
from .models import User
from .serializers import (AdminUserSerializer, ChangePasswordSerializer, LoginSerializer,
                          PasswordResetConfirmSerializer, PasswordResetRequestSerializer,
                          RegisterSerializer, UserSerializer, VerifyEmailSerializer)
from .services import send_verification_email
from .tokens import email_verification_token


@method_decorator(csrf_protect, name="dispatch")
class CsrfCookieView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = []

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        from django.middleware.csrf import get_token
        token = get_token(request)
        return Response({'detail': 'CSRF cookie set.', 'csrfToken': token})


@method_decorator(csrf_protect, name="dispatch")
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'register'

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        send_verification_email(user)
        refresh = RefreshToken.for_user(user)
        response = Response({'user': UserSerializer(user).data}, status=status.HTTP_201_CREATED)
        return set_auth_cookies(response, str(refresh.access_token), str(refresh))


@method_decorator(csrf_protect, name="dispatch")
class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        response = Response({'user': data['user']})
        return set_auth_cookies(response, data['access'], data['refresh'])


@method_decorator(csrf_protect, name="dispatch")

class CookieTokenRefreshView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        refresh = request.COOKIES.get('techvoto_refresh')
        if not refresh:
            return Response({'detail': 'Refresh session is missing.'}, status=401)
        serializer = TokenRefreshSerializer(data={'refresh': refresh})
        try:
            serializer.is_valid(raise_exception=True)
        except (InvalidToken, TokenError):
            # Concurrent tab refreshes: if a new refresh token was already
            # minted within the last 10 seconds, accept the current access cookie.
            access = request.COOKIES.get('techvoto_access')
            if access:
                from rest_framework_simplejwt.tokens import AccessToken
                try:
                    AccessToken(access)  # still valid — let the client keep it
                    return Response({'detail': 'Session still valid.'})
                except TokenError:
                    pass
            response = Response({'detail': 'Session expired. Please sign in again.'}, status=401)
            return clear_auth_cookies(response)

        data = serializer.validated_data
        response = Response({'detail': 'Session refreshed.'})
        return set_auth_cookies(response, data['access'], data.get('refresh'))

@method_decorator(csrf_protect, name="dispatch")
class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            refresh = request.COOKIES.get('techvoto_refresh') or request.data.get('refresh', '')
            RefreshToken(refresh).blacklist()
        except TokenError:
            pass
        return clear_auth_cookies(Response(status=status.HTTP_205_RESET_CONTENT))


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_object(self):
        return self.request.user


class ChangePasswordView(APIView):
    def post(self, request):
        s = ChangePasswordSerializer(data=request.data, context={'request': request})
        s.is_valid(raise_exception=True)
        request.user.set_password(s.validated_data['new_password'])
        request.user.save(update_fields=['password'])
        return Response({'detail': 'Password updated.'})


class PasswordResetRequestView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'password_reset'

    def post(self, request):
        s = PasswordResetRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = User.objects.filter(email__iexact=s.validated_data['email'], is_active=True).first()
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            link = f'{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}'
            safe_send_mail('Reset your Techvoto password',
                           f'Hi {user.first_name},\n\nUse this link to reset your password:\n{link}\n\n'
                           'If you did not request this, ignore this email.',
                           [user.email])
        # Same response whether or not the account exists (prevents email enumeration).
        return Response({'detail': 'If that email exists, a reset link has been sent.'})


class PasswordResetConfirmView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'password_reset'

    def post(self, request):
        s = PasswordResetConfirmSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(s.validated_data['uid'])))
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            user = None
        if not user or not default_token_generator.check_token(user, s.validated_data['token']):
            return Response({'detail': 'This reset link is invalid or has expired.'}, status=400)
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError
        try:
            validate_password(s.validated_data['new_password'], user)
        except ValidationError as e:
            return Response({'new_password': list(e.messages)}, status=400)
        user.set_password(s.validated_data['new_password'])
        user.save(update_fields=['password'])
        return Response({'detail': 'Password has been reset.'})


class AdminUserViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                       viewsets.GenericViewSet):
    """Admin-only user management: change role, activate/deactivate."""
    queryset = User.objects.only('id', 'email', 'first_name', 'last_name', 'role', 'is_active', 'email_verified', 'xp', 'date_joined').order_by('-date_joined')
    serializer_class = AdminUserSerializer
    permission_classes = [IsAdminRole]
    filter_backends = [SearchFilter]
    search_fields = ['email', 'first_name', 'last_name']
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_queryset(self):
        qs = super().get_queryset()
        role = self.request.query_params.get('role')
        return qs.filter(role=role) if role else qs

    def perform_update(self, serializer):
        target = serializer.instance
        if target.pk == self.request.user.pk and (
                serializer.validated_data.get('role', target.role) != 'admin'
                or serializer.validated_data.get('is_active', True) is False):
            from rest_framework.exceptions import ValidationError
            raise ValidationError('You cannot demote or deactivate your own account.')
        serializer.save()


class VerifyEmailView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'

    def post(self, request):
        s = VerifyEmailSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(s.validated_data['uid'])))
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            user = None
        if not user or not email_verification_token.check_token(user, s.validated_data['token']):
            return Response({'detail': 'This verification link is invalid or has expired.'}, status=400)
        if not user.email_verified:
            user.email_verified = True
            user.save(update_fields=['email_verified'])
        return Response({'detail': 'Email verified. You can now enroll in courses.'})


class ResendVerificationView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'verify'

    def post(self, request):
        if request.user.email_verified:
            return Response({'detail': 'Your email is already verified.'})
        send_verification_email(request.user)
        return Response({'detail': 'Verification email sent.'})
