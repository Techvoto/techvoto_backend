
from rest_framework.exceptions import PermissionDenied
from django.middleware.csrf import CsrfViewMiddleware
from django.http import HttpResponse
from rest_framework_simplejwt.authentication import JWTAuthentication

class CookieJWTAuthentication(JWTAuthentication):
    """JWT authentication from HttpOnly cookies, with CSRF validation for unsafe methods.

    Bearer authentication remains available for trusted API clients and integrations.
    Browser sessions use the cookie path and must pass Django's CSRF check.
    """
    def authenticate(self, request):
        raw_token = request.COOKIES.get('techvoto_access')
        if not raw_token:
            return super().authenticate(request)
        validated_token = self.get_validated_token(raw_token)
        self._enforce_csrf(request)
        return self.get_user(validated_token), validated_token

    @staticmethod
    def _enforce_csrf(request):
        check = CsrfViewMiddleware(lambda req: HttpResponse())
        reason = check.process_view(request, lambda req: HttpResponse(), (), {})
        if reason:
            raise PermissionDenied(f'CSRF verification failed: {reason}')
