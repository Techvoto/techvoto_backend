from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.testing import make_course, make_user
from .models import Certificate, Enrollment


class CourseAccessTests(TestCase):
    def setUp(self):
        self.teacher = make_user('t@x.com', 'instructor')
        self.student = make_user('s@x.com')
        self.c = APIClient()

    def test_public_detail_hides_lesson_content_and_video(self):
        course, _ = make_course(self.teacher)
        body = str(self.c.get(f'/api/courses/{course.slug}/').data)
        self.assertNotIn('secret.mp4', body)
        self.assertNotIn('SECRET BODY', body)

    def test_lesson_requires_enrollment_unless_preview(self):
        course, (lesson,) = make_course(self.teacher)
        self.c.force_authenticate(self.student)
        self.assertEqual(self.c.get(f'/api/lessons/{lesson.id}/').status_code, 403)
        lesson.is_free_preview = True
        lesson.save()
        self.assertEqual(self.c.get(f'/api/lessons/{lesson.id}/').status_code, 200)
        lesson.is_free_preview = False
        lesson.save()
        self.assertEqual(self.c.post(f'/api/courses/{course.slug}/enroll/').status_code, 201)
        self.assertEqual(self.c.get(f'/api/lessons/{lesson.id}/').status_code, 200)

    def test_paid_course_needs_payment(self):
        course, _ = make_course(self.teacher, price_kobo=500000)
        self.c.force_authenticate(self.student)
        self.assertEqual(self.c.post(f'/api/courses/{course.slug}/enroll/').status_code, 402)
        self.assertFalse(Enrollment.objects.exists())

    def test_xp_only_awarded_once_per_lesson(self):
        course, (lesson,) = make_course(self.teacher)
        Enrollment.objects.create(user=self.student, course=course)
        self.c.force_authenticate(self.student)
        first = self.c.post(f'/api/lessons/{lesson.id}/complete/')
        second = self.c.post(f'/api/lessons/{lesson.id}/complete/')
        self.assertEqual((first.data['xp_awarded'], second.data['xp_awarded']), (20, 0))
        self.student.refresh_from_db()
        self.assertEqual(self.student.xp, 20)
        self.assertEqual(self.student.streak, 1)

    def test_completing_all_lessons_issues_certificate(self):
        course, lessons = make_course(self.teacher, lessons=2)
        Enrollment.objects.create(user=self.student, course=course)
        self.c.force_authenticate(self.student)
        for lesson in lessons:
            self.c.post(f'/api/lessons/{lesson.id}/complete/')
        self.assertTrue(Certificate.objects.filter(user=self.student, course=course).exists())

    def test_instructor_cannot_edit_someone_elses_course(self):
        other = make_user('o@x.com', 'instructor')
        course, _ = make_course(self.teacher)
        self.c.force_authenticate(other)
        self.assertEqual(self.c.patch(f'/api/courses/{course.slug}/', {'title': 'Hacked'}, format='json').status_code, 403)

    def test_student_cannot_create_course(self):
        self.c.force_authenticate(self.student)
        r = self.c.post('/api/courses/', {'title': 'Mine'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_cannot_publish_empty_course(self):
        self.c.force_authenticate(self.teacher)
        r = self.c.post('/api/courses/', {'title': 'Empty', 'status': 'published'}, format='json')
        self.assertEqual(r.status_code, 400)
