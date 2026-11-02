import sys
from datetime import timedelta
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env()
environ.Env.read_env(BASE_DIR / '.env')

DEBUG = env.bool('DEBUG', default=False)
SECRET_KEY = env('SECRET_KEY', default='')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-local-development-only-key'
    else:
        raise ImproperlyConfigured('SECRET_KEY must be set when DEBUG=False.')
if not DEBUG and (SECRET_KEY.startswith('django-insecure-') or 'replace-with' in SECRET_KEY.lower()):
    raise ImproperlyConfigured('Replace the example SECRET_KEY before deploying.')

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])
FRONTEND_URL = env('FRONTEND_URL', default='http://localhost:3000').rstrip('/')

INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'rest_framework', 'rest_framework_simplejwt', 'rest_framework_simplejwt.token_blacklist',
    'corsheaders', 'drf_spectacular', 'django_filters', 'django_celery_results',
    'apps.core', 'apps.users', 'apps.courses', 'apps.assessments',
    'apps.liveclasses', 'apps.payments', 'apps.engagement', 'apps.support',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'apps.core.middleware.RequestObservabilityMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'techvoto.urls'
AUTH_USER_MODEL = 'users.User'
WSGI_APPLICATION = 'techvoto.wsgi.application'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [], 'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.debug', 'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages',
    ]},
}]


DATABASES = {'default': env.db('DATABASE_URL', default=f'sqlite:///{BASE_DIR / "db.sqlite3"}')}
if not DATABASES['default']['ENGINE'].endswith('sqlite3'):
    DATABASES['default']['CONN_MAX_AGE'] = env.int('DB_CONN_MAX_AGE', default=60)
    DATABASES['default']['CONN_HEALTH_CHECKS'] = True
    # Cap connect attempts so an unreachable DB fails fast instead of hanging a request for minutes.
    DATABASES['default'].setdefault('OPTIONS', {})['connect_timeout'] = env.int('DB_CONNECT_TIMEOUT', default=10)

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Lagos'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # request bodies (non-file) capped at 10 MB

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ('apps.users.authentication.CookieJWTAuthentication',),
    # Secure by default: every endpoint needs login unless it explicitly opens itself up.
    'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.IsAuthenticated',),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    # JSON only in production: no browsable API (it renders HTML forms and leaks structure).
    'DEFAULT_RENDERER_CLASSES': (['rest_framework.renderers.JSONRenderer'] if not DEBUG else
                                 ['rest_framework.renderers.JSONRenderer', 'rest_framework.renderers.BrowsableAPIRenderer']),
    # Number of reverse proxies in front of Django. Throttling keys on the real client IP, so this must be right:
    # Vercel -> Render is 2 (the Next.js server forwards the visitor's IP, Render appends the Vercel egress IP).
    'NUM_PROXIES': env.int('NUM_PROXIES', default=2),
    'DEFAULT_PAGINATION_CLASS': 'apps.core.pagination.StandardPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend'],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle', 'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '120/min', 'user': '600/min',
        'auth': '10/min', 'register': '10/hour', 'password_reset': '5/hour', 'checkout': '20/hour',
        'verify': '5/hour', 'contact': '5/hour',
    },
}

AUTH_COOKIE_SECURE = env.bool('AUTH_COOKIE_SECURE', default=not DEBUG)
AUTH_COOKIE_SAMESITE = env('AUTH_COOKIE_SAMESITE', default='Lax')
AUTH_COOKIE_DOMAIN = env('AUTH_COOKIE_DOMAIN', default='')
CSRF_COOKIE_SAMESITE = AUTH_COOKIE_SAMESITE
CSRF_COOKIE_DOMAIN = AUTH_COOKIE_DOMAIN or None
if not DEBUG and not AUTH_COOKIE_SECURE:
    raise ImproperlyConfigured('AUTH_COOKIE_SECURE must be True in production.')
if AUTH_COOKIE_SAMESITE.lower() == 'none' and not AUTH_COOKIE_SECURE:
    raise ImproperlyConfigured('SameSite=None cookies require AUTH_COOKIE_SECURE=True.')

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'AUTH_COOKIE_HTTP_ONLY': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=['http://localhost:3000'])
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=['http://localhost:3000'])

# Throttle counters live in the cache. LocMemCache is per-process, so with several gunicorn workers the limits are
# multiplied by the worker count. Set CACHE_URL (e.g. rediss://:pass@host:6379/0 or dbcache://throttle_cache) in prod.
#
# --- CANONICAL CACHES DEFINITION (do not redefine below) ---
CACHES = {'default': env.cache_url('CACHE_URL', default='locmemcache://')}

# Fail fast on the two cache misconfigurations that silently weaken security:
# 1) LocMemCache in production (throttles multiply by worker count).
# 2) CACHE_URL and CELERY_BROKER_URL pointing at the same Redis database (evictions drop queued tasks).
if not DEBUG:
    _cache_backend = CACHES['default'].get('BACKEND', '')
    _cache_location = str(CACHES['default'].get('LOCATION', ''))
    _broker_url = env('CELERY_BROKER_URL', default='')

    if _cache_backend.endswith('LocMemCache'):
        if not env.bool('ALLOW_LOCMEMCACHE', default=False):
            raise ImproperlyConfigured(
                'LocMemCache is per-process; throttles multiply by worker count. '
                'Set CACHE_URL (Redis or dbcache://) in production, '
                'or set ALLOW_LOCMEMCACHE=true if you truly run one worker.'
            )

    _norm = lambda u: u.rstrip('/').lower() if u else u
    if _broker_url.startswith(('redis://', 'rediss://')) and _cache_backend.endswith('RedisCache'):
        if _cache_location and _norm(_cache_location) == _norm(_broker_url):
            raise ImproperlyConfigured(
                'CACHE_URL and CELERY_BROKER_URL must not point to the same Redis URL. '
                'A cache eviction policy (e.g. allkeys-lru) would silently drop tasks.'
            )
# --- END CANONICAL CACHES DEFINITION ---

EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='Techvoto <noreply@techvoto.com>')

PAYSTACK_SECRET_KEY = env('PAYSTACK_SECRET_KEY', default='')
PAYSTACK_BASE_URL = 'https://api.paystack.co'
REFUND_WINDOW_DAYS = env.int('REFUND_WINDOW_DAYS', default=7)
REFUND_MAX_PROGRESS = env.int('REFUND_MAX_PROGRESS', default=30)

CONTACT_EMAIL = env('CONTACT_EMAIL', default='support@techvoto.com')


# ==============================================================================
# JITSI & 8x8 JaaS CONFIGURATION
# ==============================================================================
JITSI_DOMAIN = env('JITSI_DOMAIN', default='8x8.vc')
JITSI_APP_ID = env('JITSI_APP_ID', default='')
JITSI_KID = env('JITSI_KID', default='')
JITSI_APP_SECRET = env('JITSI_APP_SECRET', default='')

JITSI_PRIVATE_KEY_PATH = Path(env('JITSI_PRIVATE_KEY_PATH',
                                  default=str(BASE_DIR / 'jitsi_private.key')))
if JITSI_APP_ID and JITSI_KID:
    if not JITSI_PRIVATE_KEY_PATH.exists():
        raise ImproperlyConfigured(
            f'JaaS is configured (JITSI_APP_ID/JITSI_KID) but {JITSI_PRIVATE_KEY_PATH} is missing. '
            'Provide the key file at deploy time or remove JITSI_APP_ID.'
        )
    JITSI_PRIVATE_KEY = JITSI_PRIVATE_KEY_PATH.read_bytes()
else:
    JITSI_PRIVATE_KEY = b''


SPECTACULAR_SETTINGS = {
    'TITLE': 'Techvoto LMS API', 'DESCRIPTION': 'API for the Techvoto learning platform.',
    'VERSION': '2.0.0', 'SERVE_INCLUDE_SCHEMA': False,
}

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')  # Render/most hosts terminate TLS upstream
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False)
    SECURE_HSTS_PRELOAD = env.bool('SECURE_HSTS_PRELOAD', default=False)
    SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)
    # request.path begins with '/'. Match the health endpoint so host probes still answer over HTTP.
    SECURE_REDIRECT_EXEMPT = [r'^/api/health/$']
    SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
    SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    CSRF_COOKIE_SAMESITE = AUTH_COOKIE_SAMESITE
    CSRF_COOKIE_DOMAIN = AUTH_COOKIE_DOMAIN or None
    CSRF_COOKIE_HTTPONLY = True  # React receives a masked token from /auth/csrf/; the cookie itself need not be readable
    X_FRAME_OPTIONS = 'DENY'

# Interactive API docs are off in production unless explicitly enabled.
EXPOSE_API_DOCS = env.bool('EXPOSE_API_DOCS', default=DEBUG)


# Celery: Redis broker + Django database result backend. Use a dedicated Redis database/instance in production.
# NOTE: send_email_task should declare ignore_result=True; CELERY_TASK_IGNORE_RESULT here only covers
# tasks that do not override it.
CELERY_BROKER_URL = env('CELERY_BROKER_URL', default='redis://127.0.0.1:6380/1')
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND', default='django-db://')
CELERY_TASK_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 240
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_RESULT_EXPIRES = 86400
CELERY_TASK_IGNORE_RESULT = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_MAX_RETRIES = 5


# Sentry: optional. Set SENTRY_DSN in production to capture backend errors and traces.
SENTRY_DSN = env('SENTRY_DSN', default='')
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        environment=env('SENTRY_ENVIRONMENT', default='production' if not DEBUG else 'development'),
        release=env('SENTRY_RELEASE', default='techvoto@dev'),
        traces_sample_rate=env.float('SENTRY_TRACES_SAMPLE_RATE', default=0.05),
        send_default_pii=False,
    )


# Logging MUST be defined before any logger.warning(...) call below.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'std': {'format': '%(asctime)s %(levelname)s %(name)s: %(message)s'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'std'}},
    'root': {'handlers': ['console'], 'level': env('LOG_LEVEL', default='INFO')},
    'loggers': {
        'django.request': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
        'techvoto.request': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'celery': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
    },
}

if not DEBUG and not SENTRY_DSN:
    import logging
    logging.getLogger('techvoto').warning(
        'SENTRY_DSN is empty — production errors will not be reported.'
    )


# ---------------------------------------------------------------------------
# Test-only overrides. MUST come last so they override anything read from .env.
# ---------------------------------------------------------------------------
if 'test' in sys.argv:
    SECURE_SSL_REDIRECT = False
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
    EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    SENTRY_DSN = ''  # never let tests push events to Sentry