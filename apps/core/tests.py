from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.testing import make_course, make_user


class SearchTests(TestCase):
    def setUp(self):
        self.teacher = make_user('t@x.com', 'instructor')
        self.c = APIClient()

    def test_finds_published_courses_only(self):
        pub, _ = make_course(self.teacher)
        pub.title = 'Python Basics'
        pub.save()
        draft, _ = make_course(self.teacher, published=False)
        draft.title = 'Python Secrets'
        draft.save()
        r = self.c.get('/api/search/?q=python')
        titles = [c['title'] for c in r.data['courses']]
        self.assertIn('Python Basics', titles)
        self.assertNotIn('Python Secrets', titles)

    def test_short_query_returns_nothing(self):
        make_course(self.teacher)
        r = self.c.get('/api/search/?q=a')
        self.assertEqual(r.data, {'courses': [], 'instructors': [], 'lessons': []})

    def test_finds_instructors_with_published_courses(self):
        make_course(self.teacher)
        r = self.c.get('/api/search/?q=Instructor')   # make_user names them "Test Instructor"
        self.assertEqual(len(r.data['instructors']), 1)

    def test_stats_are_role_protected(self):
        self.c.force_authenticate(make_user('s@x.com'))
        self.assertEqual(self.c.get('/api/stats/admin/').status_code, 403)
        self.assertEqual(self.c.get('/api/stats/instructor/').status_code, 403)


class HealthAndMediaTests(TestCase):
    def test_health_is_public_and_ok(self):
        r = APIClient().get('/api/health/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, {'status': 'ok'})

    def test_private_upload_folders_are_never_served_directly(self):
        # Lesson files and submissions must only be reachable through the permission-checked API views.
        for path in ('/media/lesson_resources/a.pdf', '/media/submissions/a.pdf'):
            self.assertEqual(APIClient().get(path).status_code, 404)


    def test_health_is_public_and_ok(self):
        r = APIClient().get('/api/health/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['status'], 'ok')
        self.assertEqual(r.data['checks'], {'database': True, 'cache': True})

    def test_health_reports_degraded_when_dependency_fails(self):
        from unittest import mock
        with mock.patch('apps.core.views.connection.cursor',
                        side_effect=Exception('db down')):
            r = APIClient().get('/api/health/')
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.data['status'], 'degraded')
        self.assertFalse(r.data['checks']['database'])