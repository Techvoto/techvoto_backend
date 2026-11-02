from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.testing import make_course, make_user
from apps.courses.models import Enrollment
from .models import Attendance, LiveClass


class LiveClassTests(TestCase):
    def setUp(self):
        self.teacher, self.student = make_user('t@x.com', 'instructor'), make_user('s@x.com')
        self.course, _ = make_course(self.teacher)
        self.c = APIClient()

    def make_class(self, minutes_from_now):
        return LiveClass.objects.create(course=self.course, host=self.teacher, title='Live',
                                        starts_at=timezone.now() + timedelta(minutes=minutes_from_now))

    def test_unenrolled_user_cannot_join(self):
        live = self.make_class(0)
        self.c.force_authenticate(self.student)
        self.assertEqual(self.c.post(f'/api/live-classes/{live.id}/join/').status_code, 404)  # not even visible

    def test_student_cannot_join_before_window(self):
        Enrollment.objects.create(user=self.student, course=self.course)
        live = self.make_class(120)
        self.c.force_authenticate(self.student)
        self.assertEqual(self.c.post(f'/api/live-classes/{live.id}/join/').status_code, 400)

    def test_student_joins_in_window_and_attendance_recorded(self):
        Enrollment.objects.create(user=self.student, course=self.course)
        live = self.make_class(5)
        self.c.force_authenticate(self.student)
        r = self.c.post(f'/api/live-classes/{live.id}/join/')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data['is_moderator'])
        self.assertTrue(Attendance.objects.filter(live_class=live, user=self.student).exists())

    def test_host_join_starts_class_and_is_moderator(self):
        live = self.make_class(300)
        self.c.force_authenticate(self.teacher)
        r = self.c.post(f'/api/live-classes/{live.id}/join/')
        self.assertTrue(r.data['is_moderator'])
        live.refresh_from_db()
        self.assertEqual(live.status, 'live')

    def test_room_name_never_in_listing(self):
        Enrollment.objects.create(user=self.student, course=self.course)
        live = self.make_class(5)
        self.c.force_authenticate(self.student)
        self.assertNotIn(live.room_name, str(self.c.get('/api/live-classes/').data))

    def test_student_cannot_schedule_class(self):
        self.c.force_authenticate(self.student)
        r = self.c.post('/api/live-classes/', {'course': self.course.id, 'title': 'x',
                                               'starts_at': (timezone.now() + timedelta(days=1)).isoformat()},
                        format='json')
        self.assertEqual(r.status_code, 403)

    def test_jitsi_misconfiguration_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        from django.test import override_settings
        from .services import jitsi_connection
        live = self.make_class(0)
        with override_settings(JITSI_APP_ID='vpaas', JITSI_KID='', JITSI_PRIVATE_KEY=b'',
                            JITSI_APP_SECRET=''):
            with self.assertRaises(ImproperlyConfigured):
                jitsi_connection(self.teacher, live, is_moderator=True)