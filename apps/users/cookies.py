from django.conf import settings
from django.middleware.csrf import get_token
from rest_framework.response import Response

ACCESS_COOKIE = 'techvoto_access'
REFRESH_COOKIE = 'techvoto_refresh'


def set_auth_cookies(response, access, refresh=None):
    common = {
        'secure': settings.AUTH_COOKIE_SECURE,
        'httponly': True,
        'samesite': settings.AUTH_COOKIE_SAMESITE,
        'domain': settings.AUTH_COOKIE_DOMAIN or None,
    }
    response.set_cookie(ACCESS_COOKIE, access, max_age=int(settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds()), path='/', **common)
    if refresh:
        response.set_cookie(REFRESH_COOKIE, refresh, max_age=int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds()), path='/api/auth/', **common)
    return response


def clear_auth_cookies(response):
    domain = settings.AUTH_COOKIE_DOMAIN or None
    response.delete_cookie(ACCESS_COOKIE, path='/', domain=domain, samesite=settings.AUTH_COOKIE_SAMESITE)
    response.delete_cookie(REFRESH_COOKIE, path='/api/auth/', domain=domain, samesite=settings.AUTH_COOKIE_SAMESITE)
    return response


def csrf_response(request):
    response = Response({'detail': 'CSRF cookie set.'})
    get_token(request)
    return response
