from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.testing import PASSWORD, make_user
from .models import User


class AuthSecurityTests(TestCase):
    def setUp(self):
        self.c = APIClient()

    def test_registration_cannot_choose_role(self):
        r = self.c.post('/api/auth/register/', {'email': 'a@x.com', 'first_name': 'A', 'last_name': 'B',
                                                 'password': PASSWORD, 'password2': PASSWORD, 'role': 'admin'},
                        format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(User.objects.get(email='a@x.com').role, 'student')

    def test_user_cannot_change_own_role_or_xp(self):
        u = make_user('s@x.com')
        self.c.force_authenticate(u)
        r = self.c.patch('/api/auth/me/', {'role': 'admin', 'xp': 99999, 'bio': 'hi'}, format='json')
        self.assertEqual(r.status_code, 200)
        u.refresh_from_db()
        self.assertEqual((u.role, u.xp, u.bio), ('student', 0, 'hi'))

    def test_only_admin_can_manage_users(self):
        student, admin = make_user('s@x.com'), make_user('adm@x.com', 'admin')
        target = make_user('t@x.com')
        self.c.force_authenticate(student)
        self.assertEqual(self.c.get('/api/auth/admin/users/').status_code, 403)
        self.c.force_authenticate(admin)
        r = self.c.patch(f'/api/auth/admin/users/{target.id}/', {'role': 'instructor'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        target.refresh_from_db()
        self.assertEqual(target.role, 'instructor')

    def test_admin_cannot_demote_self(self):
        admin = make_user('adm@x.com', 'admin')
        self.c.force_authenticate(admin)
        r = self.c.patch(f'/api/auth/admin/users/{admin.id}/', {'role': 'student'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_password_reset_does_not_reveal_accounts(self):
        make_user('real@x.com')
        a = self.c.post('/api/auth/password-reset/', {'email': 'real@x.com'}, format='json')
        b = self.c.post('/api/auth/password-reset/', {'email': 'nobody@x.com'}, format='json')
        self.assertEqual((a.status_code, a.data), (b.status_code, b.data))



    def test_login_returns_user_and_sets_auth_cookies(self):
        make_user('l@x.com')
        r = self.c.post('/api/auth/login/', {'email': 'l@x.com', 'password': PASSWORD}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertIn('user', r.data)
        self.assertEqual(r.data['user']['role'], 'student')
        # Tokens are delivered via HttpOnly cookies, never in the JSON body.
        self.assertNotIn('access', r.data)
        self.assertNotIn('refresh', r.data)
        self.assertIn('techvoto_access', r.cookies)
        self.assertIn('techvoto_refresh', r.cookies)
        self.assertTrue(r.cookies['techvoto_access']['httponly'])
        self.assertTrue(r.cookies['techvoto_refresh']['httponly'])
        # Refresh cookie is scoped to /api/auth/ so it is not sent on every API request.
        self.assertEqual(r.cookies['techvoto_refresh']['path'], '/api/auth/')


class EmailVerificationTests(TestCase):
    def setUp(self):
        self.c = APIClient()

    def register(self, email='new@x.com'):
        return self.c.post('/api/auth/register/', {'email': email, 'first_name': 'N', 'last_name': 'U',
                                                    'password': PASSWORD, 'password2': PASSWORD}, format='json')

    def test_register_sends_email_and_starts_unverified(self):
        from django.core import mail
        self.assertEqual(self.register().status_code, 201)
        self.assertFalse(User.objects.get(email='new@x.com').email_verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/verify-email?uid=', mail.outbox[0].body)

    def _token(self, user):
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        from .tokens import email_verification_token
        return urlsafe_base64_encode(force_bytes(user.pk)), email_verification_token.make_token(user)

    def test_valid_token_verifies_and_bad_token_does_not(self):
        self.register()
        user = User.objects.get(email='new@x.com')
        uid, token = self._token(user)
        bad = self.c.post('/api/auth/verify-email/', {'uid': uid, 'token': token + 'x'}, format='json')
        self.assertEqual(bad.status_code, 400)
        ok = self.c.post('/api/auth/verify-email/', {'uid': uid, 'token': token}, format='json')
        self.assertEqual(ok.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.email_verified)

    def test_unverified_user_cannot_enroll(self):
        from apps.core.testing import make_course
        teacher = make_user('t@x.com', 'instructor')
        course, _ = make_course(teacher)
        student = make_user('s@x.com', email_verified=False)
        self.c.force_authenticate(student)
        r = self.c.post(f'/api/courses/{course.slug}/enroll/')
        self.assertEqual(r.status_code, 403)
        self.assertIn('verify', str(r.data['detail']).lower())

    def test_login_does_not_invalidate_verification_link(self):
        self.register()
        user = User.objects.get(email='new@x.com')
        uid, token = self._token(user)
        self.c.post('/api/auth/login/', {'email': 'new@x.com', 'password': PASSWORD}, format='json')   # updates last_login
        r = self.c.post('/api/auth/verify-email/', {'uid': uid, 'token': token}, format='json')
        self.assertEqual(r.status_code, 200)
