from django.db import connection
from django.core.cache import cache
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.db.models import Count, Q, Sum
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.courses.models import Course, Enrollment, Lesson
from apps.payments.models import Payment
from apps.users.models import User
from .permissions import IsAdminRole, IsInstructorOrAdmin


class AdminStatsView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        revenue = Payment.objects.filter(status='success').aggregate(t=Sum('amount_kobo'))['t'] or 0
        return Response({
            'users': {r['role']: r['n'] for r in User.objects.values('role').annotate(n=Count('id'))},
            'courses': {r['status']: r['n'] for r in Course.objects.values('status').annotate(n=Count('id'))},
            'enrollments': Enrollment.objects.count(),
            'completions': Enrollment.objects.filter(completed_at__isnull=False).count(),
            'revenue_kobo': revenue,
        })


class InstructorStatsView(APIView):
    permission_classes = [IsInstructorOrAdmin]

    def get(self, request):
        courses = Course.objects.filter(instructor=request.user)
        enrollments = Enrollment.objects.filter(course__in=courses)
        revenue = Payment.objects.filter(course__in=courses, status='success').aggregate(t=Sum('amount_kobo'))['t'] or 0
        return Response({
            'courses': courses.count(),
            'published': courses.filter(status='published').count(),
            'students': enrollments.values('user').distinct().count(),
            'completions': enrollments.filter(completed_at__isnull=False).count(),
            'revenue_kobo': revenue,
            'per_course': list(courses.annotate(students=Count('enrollments')).values('title', 'slug', 'students')),
        })


class SearchView(APIView):
    """Public search across published courses, instructors and lesson titles (titles are already public in curricula)."""
    permission_classes = [AllowAny]

    @method_decorator(cache_page(30))
    def get(self, request):
        q = ' '.join((request.query_params.get('q') or '').split())[:80]
        if len(q) < 2:
            return Response({'courses': [], 'instructors': [], 'lessons': []})
        pub = Course.objects.filter(status='published').select_related('instructor', 'category').only('id', 'title', 'slug', 'subtitle', 'level', 'price_kobo', 'instructor__first_name', 'instructor__last_name', 'category__name')
        courses = pub.filter(Q(title__icontains=q) | Q(subtitle__icontains=q) | Q(description__icontains=q) | Q(category__name__icontains=q)
                             | Q(instructor__first_name__icontains=q) | Q(instructor__last_name__icontains=q))[:6]
        instructors = User.objects.filter(role='instructor', is_active=True, taught_courses__status='published').only('id', 'first_name', 'last_name', 'bio') \
            .filter(Q(first_name__icontains=q) | Q(last_name__icontains=q)) \
            .annotate(course_count=Count('taught_courses', filter=Q(taught_courses__status='published'))).distinct()[:4]
        lessons = Lesson.objects.filter(title__icontains=q, section__course__status='published') \
            .select_related('section__course').only('id', 'title', 'section__course__title', 'section__course__slug')[:6]
        return Response({
            'courses': [{'id': c.id, 'title': c.title, 'slug': c.slug, 'subtitle': c.subtitle, 'level': c.level,
                         'price_kobo': c.price_kobo, 'instructor': c.instructor.full_name,
                         'category': c.category.name if c.category else None} for c in courses],
            'instructors': [{'id': u.id, 'full_name': u.full_name, 'bio': u.bio[:120], 'course_count': u.course_count}
                            for u in instructors],
            'lessons': [{'id': l.id, 'title': l.title, 'course_title': l.section.course.title,
                         'course_slug': l.section.course.slug} for l in lessons],
        })


class HealthView(APIView):
    """Liveness/readiness probe for the host's health check. Unauthenticated, unthrottled, touches the DB once."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    def get(self, request):
        checks = {'database': False, 'cache': False}
        try:
            with connection.cursor() as cur:
                cur.execute('SELECT 1')
            checks['database'] = True
        except Exception:  # noqa: BLE001
            pass
        try:
            cache_key = 'health:probe'
            cache.set(cache_key, 'ok', timeout=5)
            checks['cache'] = cache.get(cache_key) == 'ok'
            cache.delete(cache_key)
        except Exception:  # noqa: BLE001
            pass
        healthy = all(checks.values())
        return Response({'status': 'ok' if healthy else 'degraded', 'checks': checks}, status=200 if healthy else 503)
