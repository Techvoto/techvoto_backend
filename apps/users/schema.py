# apps/users/schema.py
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class CookieJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = 'apps.users.authentication.CookieJWTAuthentication'
    name = 'cookieAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'cookie',
            'name': 'techvoto_access',
            'description': (
                'Browser clients: HttpOnly cookie set by /api/auth/login/. '
                'Server/integration clients may instead send `Authorization: Bearer <jwt>`.'
            ),
        }