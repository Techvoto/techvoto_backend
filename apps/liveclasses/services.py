import time
from datetime import timedelta

import jwt
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

EARLY_JOIN = timedelta(minutes=15)
LATE_GRACE = timedelta(minutes=60)


def join_window_open(live_class, now=None):
    now = now or timezone.now()
    end = live_class.starts_at + timedelta(minutes=live_class.duration_minutes) + LATE_GRACE
    return live_class.starts_at - EARLY_JOIN <= now <= end


def _load_private_key():
    key = settings.JITSI_PRIVATE_KEY
    if not key:
        raise ImproperlyConfigured(
            'JITSI_APP_ID/JITSI_KID are set but no JITSI_PRIVATE_KEY was provided. '
            'Place the PEM file at settings.JITSI_PRIVATE_KEY_PATH or set JITSI_PRIVATE_KEY.'
        )
    if isinstance(key, str):
        key = key.encode('utf-8')
    if b'BEGIN' not in key:
        raise ImproperlyConfigured('JITSI_PRIVATE_KEY does not look like a PEM key.')
    return key


def jitsi_connection(user, live_class, is_moderator):
    """Everything the frontend needs to embed the meeting.

    - No JITSI_APP_ID: plain room on JITSI_DOMAIN (no auth; only for local development or
      a self-hosted, unauthenticated Jitsi).
    - JITSI_APP_ID + JITSI_APP_SECRET: HS256 token for self-hosted Jitsi with JWT auth.
    - JITSI_APP_ID + JITSI_KID + JITSI_PRIVATE_KEY: RS256 token for 8x8 JaaS.

    Misconfiguration fails loudly: a silently downgraded room would be an auth bypass on
    a tenant that expects JWT-protected meetings.
    """
    domain = settings.JITSI_DOMAIN
    room = live_class.room_name
    token = None
    now = int(time.time())
    ctx = {'user': {'id': str(user.id), 'name': user.full_name, 'email': user.email,
                    'moderator': 'true' if is_moderator else 'false'}}
    exp = now + int((live_class.duration_minutes + 120) * 60)

    jaas_configured = bool(settings.JITSI_APP_ID and settings.JITSI_KID and settings.JITSI_PRIVATE_KEY)
    self_hosted_jwt_configured = bool(settings.JITSI_APP_ID and settings.JITSI_APP_SECRET)

    if jaas_configured:
        room = f'{settings.JITSI_APP_ID}/{live_class.room_name}'
        payload = {'aud': 'jitsi', 'iss': 'chat', 'sub': settings.JITSI_APP_ID,
                   'room': live_class.room_name, 'nbf': now - 10, 'exp': exp, 'context': ctx}
        token = jwt.encode(payload, _load_private_key(), algorithm='RS256',
                           headers={'kid': settings.JITSI_KID})
    elif self_hosted_jwt_configured:
        payload = {'aud': 'jitsi', 'iss': settings.JITSI_APP_ID, 'sub': domain,
                   'room': live_class.room_name, 'nbf': now - 10, 'exp': exp, 'context': ctx}
        token = jwt.encode(payload, settings.JITSI_APP_SECRET, algorithm='HS256')
    elif settings.JITSI_APP_ID:
        # Partial JaaS config — refuse to hand back an unauthenticated room.
        raise ImproperlyConfigured(
            'JITSI_APP_ID is set but neither (JITSI_KID + JITSI_PRIVATE_KEY) nor '
            'JITSI_APP_SECRET is provided. Refusing to issue an unauthenticated room.'
        )

    return {'domain': domain, 'room': room, 'jwt': token,
            'display_name': user.full_name, 'email': user.email,
            'is_moderator': is_moderator}