# Techvoto LMS: backend (Django REST)

Roles: **student**, **instructor**, **admin** (single organisation).

| Area | What it does |
|---|---|
| Auth | Register (always student), HttpOnly-cookie JWT login/refresh/logout (blacklist + rotation), CSRF protected, change + reset password, throttled |
| Courses | Categories, courses (draft/published/archived, naira price), sections, lessons (video/reading/file), reviews |
| Learning | Enrollment (free or Paystack), lesson completion, progress %, XP, streaks, certificates (public verify) |
| Assessments | Quizzes (single/multiple, time limit, attempts, required-to-certify), assignments + grading, gradebook |
| Live classes | Schedule, notify students, join window, Jitsi token, attendance, end/cancel |
| Payments | Paystack checkout, return-verify, signed webhook, idempotent fulfilment |
| Engagement | Notifications, announcements, per-course discussion threads |
| Dashboards | `/api/stats/admin/`, `/api/stats/instructor/` |

## First run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # set SECRET_KEY
python manage.py makemigrations users courses assessments liveclasses payments engagement support
python manage.py migrate
python manage.py test           # run the test-suite first
python manage.py seed_data      # prints demo credentials once
python manage.py runserver
# In a second terminal, start the background worker:
celery -A techvoto worker -l INFO
```
API docs: `/api/docs/`

> The migrations folders are intentionally empty: the old project's schema is replaced
> (roles, new models) and its database was empty, so generate fresh migrations as above.
> If you have a database with real users, tell me and I'll write a data migration instead.

## Key endpoints
`/api/auth/*` · `/api/courses/` · `/api/courses/{slug}/enroll|students|reviews|gradebook/` ·
`/api/sections/` · `/api/lessons/{id}/(complete|resource)/` · `/api/enrollments/` · `/api/certificates/` ·
`/api/quizzes/{id}/(start|questions|attempts)/` · `/api/attempts/{id}/submit/` ·
`/api/assignments/{id}/(submit|submissions)/` · `/api/submissions/{id}/(grade|file)/` ·
`/api/live-classes/{id}/(join|end|cancel|attendance)/` · `/api/payments/(checkout|verify/{ref}|webhook)/` ·
`/api/notifications/` · `/api/announcements/` · `/api/threads/{id}/(replies|resolve)/` ·
`/api/search/?q=` · `/api/contact/` · `/api/contact/messages/` · `/api/auth/(verify-email|resend-verification)/` ·
`/api/payments/{id}/(request-refund|refund)/` · `/api/payments/refund-requests/{id}/(approve|reject)/`

## Paystack
Set `PAYSTACK_SECRET_KEY`. In the Paystack dashboard set the webhook URL to
`https://<your-api-host>/api/payments/webhook/`. Prices are stored in kobo and the amount charged is always
read from the course, never from the request.

## Live classes (Jitsi): read this
The public `meet.jit.si` server no longer allows free, unauthenticated iframe embedding for long meetings.
For real classes use one of:
1. **8x8 JaaS** (hosted Jitsi, free tier): set `JITSI_DOMAIN=8x8.vc`, `JITSI_APP_ID`, `JITSI_KID`, `JITSI_PRIVATE_KEY`.
2. **Self-hosted Jitsi** with JWT auth: set `JITSI_DOMAIN`, `JITSI_APP_ID`, `JITSI_APP_SECRET`.
With no Jitsi credentials the API still works and returns a plain room (fine for trying it out).

## Authentication cookies, background jobs and monitoring

- Browser authentication uses `techvoto_access` and `techvoto_refresh` cookies with `HttpOnly`; in production `AUTH_COOKIE_SECURE=True` is mandatory. The refresh cookie is scoped to `/api/auth/`. The CSRF endpoint returns a masked CSRF token to React, which keeps it in memory and sends it as `X-CSRFToken`; the separate CSRF cookie is also HttpOnly and contains no JWT.
- The React API client uses `credentials: include`, obtains a CSRF cookie before unsafe requests, and no longer stores JWTs in `localStorage`.
- Set `AUTH_COOKIE_SAMESITE=Lax` when the frontend and API are same-site (for example `app.example.com` and `api.example.com`). If they are genuinely cross-site, use `AUTH_COOKIE_SAMESITE=None`, `AUTH_COOKIE_SECURE=True`, exact CORS origins, and CSRF trusted origins. Prefer a same-origin reverse proxy where possible. Set `AUTH_COOKIE_DOMAIN` only when you understand the implications of sharing cookies across subdomains.
- Run a Redis broker and a separate Celery worker process: `celery -A techvoto worker -l INFO`. Verification, password-reset and contact emails are queued with retry/backoff. If the broker is unavailable, the mail helper logs the queue failure and falls back to synchronous SMTP.
- Run `python manage.py migrate` to install the `django_celery_results` tables. Celery results are ignored by default; the database backend is retained for operational flexibility.
- Set `SENTRY_DSN` on Django and `VITE_SENTRY_DSN` on React. Sentry captures backend exceptions, Celery task failures, frontend crashes and API/network failures (without sending default PII). Configure source-map upload in CI for readable minified frontend traces.
- Request logs include a correlation ID, method, path, status and duration; query strings and request bodies are deliberately excluded. `/api/health/` checks database and cache connectivity.

## Production notes
* Use PostgreSQL (`DATABASE_URL`). Uploaded media needs durable storage (S3/Cloudinary): Render's disk is ephemeral.
* Lesson files and assignment submissions are only downloadable through permission-checked endpoints, never by raw URL.
* Set `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `FRONTEND_URL`, email credentials.
* Set `AUTH_COOKIE_SECURE=True`; configure `AUTH_COOKIE_SAMESITE` and `AUTH_COOKIE_DOMAIN` for your exact frontend/API domains. Never use `SameSite=None` without Secure.
* Run Redis and a Celery worker (`celery -A techvoto worker -l INFO`) as a separate process. Emails are queued with retry/backoff; if Redis is unavailable, the helper logs and falls back to synchronous delivery.
* Set backend `SENTRY_DSN` and frontend `VITE_SENTRY_DSN` to enable error reporting. Configure source-map upload in CI if readable frontend stack traces are required.

## Demo data
`python manage.py seed_data` (see the top-level README). Needs `DEBUG=True` or `--force`.

## Production deployment checklist

1. **Commit migrations.** `build.sh` fails the build if they are missing or stale:
   `python manage.py makemigrations users courses assessments liveclasses payments engagement support`, then commit
   every generated `migrations/0001_initial.py` (and later ones).
2. **Environment** (Render): `DEBUG=False`, a real `SECRET_KEY`, `ALLOWED_HOSTS`, `DATABASE_URL` (PostgreSQL),
   `CORS_ALLOWED_ORIGINS`/`CSRF_TRUSTED_ORIGINS`/`FRONTEND_URL` set to the Vercel domain,
   `PAYSTACK_SECRET_KEY` (live key), real SMTP (`EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` + host/user/password).
3. **Shared cache for rate limits:** set `CACHE_URL` (Redis, or `dbcache://throttle_cache` after `createcachetable`).
   Without it each worker keeps its own counters.
4. **`NUM_PROXIES`** (default 2 = Vercel then Render). The Next.js server forwards the visitor IP so throttles apply per
   visitor, not per Vercel server. Adjust if your topology differs.
5. **Media storage:** uploaded files live on local disk. On Render add a persistent disk mounted at `backend/media`, or
   move to S3/Cloudinary. Without one, uploads vanish on every deploy.
6. **Health check path:** `/api/health/`.
7. **Paystack:** webhook URL `https://<api-host>/api/payments/webhook/` with `charge.success`, `refund.processed`, `refund.failed`.
8. API docs are disabled in production; set `EXPOSE_API_DOCS=True` to enable `/api/docs/`.
