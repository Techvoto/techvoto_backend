"""Business rules shared across apps. Keep views thin; put logic here."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.permissions import is_admin

LESSON_XP = 20


def can_access_course(user, course):
    """Enrolled students, the course's instructor, and admins."""
    if not user or not user.is_authenticated:
        return False
    if is_admin(user) or course.instructor_id == user.id:
        return True
    return course.enrollments.filter(user=user).exists()


def notify(user, title, body='', link=''):
    from apps.engagement.models import Notification
    return Notification.objects.create(user=user, title=title, body=body, link=link)


def add_xp(user, amount):
    from django.db.models import F
    type(user).objects.filter(pk=user.pk).update(xp=F('xp') + amount)
    user.refresh_from_db(fields=['xp'])


def touch_streak(user):
    today = timezone.localdate()
    last = user.last_streak_date
    if last == today:
        return
    user.streak = user.streak + 1 if last == today - timedelta(days=1) else 1
    user.last_streak_date = today
    user.save(update_fields=['streak', 'last_streak_date'])


def enroll_user(user, course, source):
    from django.db import IntegrityError
    from .models import Enrollment
    try:
        enrollment, created = Enrollment.objects.get_or_create(
            user=user, course=course, defaults={'source': source},
        )
    except IntegrityError:
        # A concurrent request won the race. Read the winner.
        enrollment = Enrollment.objects.get(user=user, course=course)
        created = False
    if created:
        notify(user, f'You are enrolled in {course.title}',
               link=f'/courses/{course.slug}')
    return enrollment, created



def course_requirements_met(enrollment):
    """All lessons done and every required quiz passed."""
    from apps.assessments.models import Quiz, QuizAttempt
    course = enrollment.course
    required = Quiz.objects.filter(course=course, is_required=True, is_published=True)
    for quiz in required:
        if not QuizAttempt.objects.filter(quiz=quiz, user=enrollment.user, passed=True).exists():
            return False
    return True


@transaction.atomic
def update_progress(enrollment):
    """Recalculate progress; issue a certificate when the course is truly complete."""
    from .models import Certificate, Lesson
    course = enrollment.course
    total = Lesson.objects.filter(section__course=course).count()
    done = enrollment.lesson_progress.filter(lesson__section__course=course).count()
    enrollment.progress_pct = round(done / total * 100) if total else 0
    if total and done >= total and enrollment.completed_at is None and course_requirements_met(enrollment):
        enrollment.completed_at = timezone.now()
        cert, created = Certificate.objects.get_or_create(user=enrollment.user, course=course)
        if created:
            notify(enrollment.user, f'Certificate earned: {course.title}', link='/certificates')
    enrollment.save(update_fields=['progress_pct', 'completed_at'])
    return enrollment
