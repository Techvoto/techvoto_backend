from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.testing import make_course, make_user
from apps.courses.models import Certificate, Enrollment
from .models import Choice, Question, Quiz, QuizAttempt


class QuizTests(TestCase):
    def setUp(self):
        self.teacher, self.student = make_user('t@x.com', 'instructor'), make_user('s@x.com')
        self.course, (self.lesson,) = make_course(self.teacher)
        Enrollment.objects.create(user=self.student, course=self.course)
        self.quiz = Quiz.objects.create(course=self.course, title='Q', pass_mark_pct=50, is_published=True,
                                        is_required=True, max_attempts=2)
        self.q = Question.objects.create(quiz=self.quiz, prompt='2+2?')
        self.right = Choice.objects.create(question=self.q, text='4', is_correct=True)
        self.wrong = Choice.objects.create(question=self.q, text='5', is_correct=False)
        self.c = APIClient()
        self.c.force_authenticate(self.student)

    def test_student_never_sees_correct_flags(self):
        r = self.c.post(f'/api/quizzes/{self.quiz.id}/start/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('is_correct', str(r.data))

    def test_grading_and_certificate_gate(self):
        self.c.post(f'/api/lessons/{self.lesson.id}/complete/')
        self.assertFalse(Certificate.objects.exists(), 'required quiz not passed yet')
        att = self.c.post(f'/api/quizzes/{self.quiz.id}/start/').data['attempt']['id']
        r = self.c.post(f'/api/attempts/{att}/submit/', {'answers': {str(self.q.id): [self.right.id]}}, format='json')
        self.assertEqual((r.data['passed'], r.data['score_pct']), (True, 100))
        self.assertTrue(Certificate.objects.filter(user=self.student).exists())

    def test_wrong_answer_fails_and_hides_answers_while_retries_remain(self):
        att = self.c.post(f'/api/quizzes/{self.quiz.id}/start/').data['attempt']['id']
        r = self.c.post(f'/api/attempts/{att}/submit/', {'answers': {str(self.q.id): [self.wrong.id]}}, format='json')
        self.assertFalse(r.data['passed'])
        self.assertNotIn('correct_choice_ids', str(r.data))

    def test_attempt_limit_enforced(self):
        for _ in range(2):
            att = self.c.post(f'/api/quizzes/{self.quiz.id}/start/').data['attempt']['id']
            self.c.post(f'/api/attempts/{att}/submit/', {'answers': {}}, format='json')
        self.assertEqual(self.c.post(f'/api/quizzes/{self.quiz.id}/start/').status_code, 400)

    def test_cannot_submit_twice(self):
        att = self.c.post(f'/api/quizzes/{self.quiz.id}/start/').data['attempt']['id']
        self.c.post(f'/api/attempts/{att}/submit/', {'answers': {}}, format='json')
        self.assertEqual(self.c.post(f'/api/attempts/{att}/submit/', {'answers': {}}, format='json').status_code, 400)

    def test_unenrolled_student_cannot_start(self):
        outsider = make_user('o@x.com')
        self.c.force_authenticate(outsider)
        self.assertIn(self.c.post(f'/api/quizzes/{self.quiz.id}/start/').status_code, (403, 404))

    def test_cannot_submit_after_time_limit_elapsed(self):
        from datetime import timedelta
        from django.utils import timezone
        self.quiz.time_limit_minutes = 5
        self.quiz.save(update_fields=['time_limit_minutes'])
        att = self.c.post(f'/api/quizzes/{self.quiz.id}/start/').data['attempt']['id']
        # Rewind the attempt's started_at past the window + grace
        QuizAttempt.objects.filter(pk=att).update(
            started_at=timezone.now() - timedelta(minutes=10))
        r = self.c.post(f'/api/attempts/{att}/submit/',
                        {'answers': {str(self.q.id): [self.right.id]}}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['score_pct'], 0)
        self.assertFalse(r.data['passed'])
        self.assertTrue(r.data['expired'])

    