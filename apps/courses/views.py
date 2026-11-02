import os

from django.db.models import Avg, Count, Q
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from apps.core.permissions import IsInstructorOrAdmin, can_manage_course, is_admin, require_verified
from .models import Category, Certificate, Course, Enrollment, Lesson, LessonProgress, Review, Section
from .serializers import (CategorySerializer, CertificateSerializer, CourseDetailSerializer,
                          CourseListSerializer, CourseWriteSerializer, EnrollmentSerializer,
                          LessonDetailSerializer, LessonWriteSerializer, ReviewSerializer,
                          SectionSerializer, SectionWriteSerializer, StudentProgressSerializer)
from .services import (LESSON_XP, add_xp, can_access_course, enroll_user, touch_streak, update_progress)

OWNER_ACTIONS = {'update', 'partial_update', 'destroy', 'students'}


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    pagination_class = None
    lookup_field = 'slug'

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [AllowAny()]
        from apps.core.permissions import IsAdminRole
        return [IsAdminRole()]


class CourseViewSet(viewsets.ModelViewSet):
    lookup_field = 'slug'
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {'level': ['exact'], 'category__slug': ['exact'], 'instructor': ['exact']}
    search_fields = ['title', 'subtitle', 'description', 'category__name']
    ordering_fields = ['published_at', 'created_at', 'price_kobo']

    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'reviews') and self.request.method in ('GET', 'HEAD', 'OPTIONS'):
            return [AllowAny()]
        if self.action == 'create':
            return [IsInstructorOrAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = Course.objects.select_related('instructor', 'category').annotate(
            avg_rating_a=Avg('reviews__rating'),
            student_count_a=Count('enrollments', distinct=True),
            lesson_count_a=Count('sections__lessons', distinct=True),
        )
        user = self.request.user
        if self.action == 'list':
            if self.request.query_params.get('mine') and user.is_authenticated:
                return qs.filter(instructor=user)
            if self.request.query_params.get('all') and is_admin(user):
                return qs
            return qs.filter(status=Course.Status.PUBLISHED)
        if not user.is_authenticated:
            return qs.filter(status=Course.Status.PUBLISHED)
        if is_admin(user):
            return qs
        return qs.filter(Q(status=Course.Status.PUBLISHED) | Q(instructor=user))

    def get_serializer_class(self):
        if self.action == 'list':
            return CourseListSerializer
        if self.action == 'retrieve':
            return CourseDetailSerializer
        return CourseWriteSerializer

    def get_object(self):
        course = super().get_object()
        if self.action in OWNER_ACTIONS and not can_manage_course(self.request.user, course):
            raise PermissionDenied('Only the course instructor or an admin can do this.')
        return course

    def perform_create(self, serializer):
        serializer.save(instructor=self.request.user)

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        self.perform_create(s)
        return Response(CourseDetailSerializer(s.instance, context=self.get_serializer_context()).data, status=201)

    def destroy(self, request, *args, **kwargs):
        course = self.get_object()
        if course.enrollments.exists():
            return Response({'detail': 'This course has students. Archive it instead of deleting.'}, status=409)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def enroll(self, request, slug=None):
        require_verified(request.user)
        course = self.get_object()
        if course.status != Course.Status.PUBLISHED:
            return Response({'detail': 'This course is not open for enrollment.'}, status=400)
        if course.instructor_id == request.user.id:
            return Response({'detail': 'You teach this course.'}, status=400)
        if not course.is_free:
            if course.enrollments.filter(user=request.user).exists():
                return Response(EnrollmentSerializer(course.enrollments.get(user=request.user)).data)
            return Response({'detail': 'Payment required.', 'price_kobo': course.price_kobo,
                             'checkout': '/api/payments/checkout/'}, status=status.HTTP_402_PAYMENT_REQUIRED)
        enrollment, created = enroll_user(request.user, course, Enrollment.Source.FREE)
        return Response(EnrollmentSerializer(enrollment).data, status=201 if created else 200)

    @action(detail=True, methods=['get'])
    def progress(self, request, slug=None):
        course = self.get_object()
        e = Enrollment.objects.filter(user=request.user, course=course).first()
        ids = list(e.lesson_progress.values_list('lesson_id', flat=True)) if e else []
        return Response({'completed_lesson_ids': ids, 'progress_pct': e.progress_pct if e else 0,
                         'completed': bool(e and e.completed_at)})

    @action(detail=True, methods=['get'])
    def students(self, request, slug=None):
        course = self.get_object()
        qs = course.enrollments.select_related('user')
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(StudentProgressSerializer(page, many=True).data)

    @action(detail=True, methods=['get', 'post'])
    def reviews(self, request, slug=None):
        course = self.get_object()
        if request.method == 'GET':
            page = self.paginate_queryset(course.reviews.select_related('user'))
            return self.get_paginated_response(ReviewSerializer(page, many=True).data)
        if not request.user.is_authenticated or not course.enrollments.filter(user=request.user).exists():
            raise PermissionDenied('Enroll in the course before reviewing it.')
        s = ReviewSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        review, _ = Review.objects.update_or_create(course=course, user=request.user, defaults={
            'rating': s.validated_data['rating'], 'comment': s.validated_data.get('comment', '')})
        return Response(ReviewSerializer(review).data, status=201)


class SectionViewSet(viewsets.ModelViewSet):
    """Instructor tooling for the course outline."""
    serializer_class = SectionWriteSerializer
    permission_classes = [IsInstructorOrAdmin]
    filterset_fields = ['course']
    pagination_class = None

    def get_queryset(self):
        qs = Section.objects.select_related('course')
        return qs if is_admin(self.request.user) else qs.filter(course__instructor=self.request.user)


class LessonViewSet(viewsets.ModelViewSet):
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_permissions(self):
        if self.action == 'retrieve':
            return [AllowAny()]       # free-preview lessons are public; others checked in get_object
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsInstructorOrAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = Lesson.objects.select_related('section__course')
        if self.action in ('update', 'partial_update', 'destroy'):
            return qs if is_admin(self.request.user) else qs.filter(section__course__instructor=self.request.user)
        return qs

    def get_serializer_class(self):
        return LessonDetailSerializer if self.action in ('retrieve',) else LessonWriteSerializer

    def retrieve(self, request, *args, **kwargs):
        lesson = self.get_object()
        course = lesson.section.course
        if not can_manage_course(request.user, course):
            if course.status != Course.Status.PUBLISHED:
                raise PermissionDenied('This course is not available.')
            if not (lesson.is_free_preview or can_access_course(request.user, course)):
                raise PermissionDenied('Enroll in this course to view the lesson.')
        return Response(LessonDetailSerializer(lesson, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        lesson = self.get_object()
        course = lesson.section.course
        enrollment = Enrollment.objects.filter(user=request.user, course=course).first()
        if not enrollment:
            raise PermissionDenied('Enroll in the course first.')
        _, created = LessonProgress.objects.get_or_create(enrollment=enrollment, lesson=lesson)
        xp = 0
        if created:   # XP and streak only on first completion — no farming by re-clicking
            add_xp(request.user, LESSON_XP)
            touch_streak(request.user)
            xp = LESSON_XP
        update_progress(enrollment)
        return Response({'lesson_id': lesson.id, 'progress_pct': enrollment.progress_pct,
                         'xp_awarded': xp, 'course_completed': enrollment.completed_at is not None})


class MyEnrollmentsView(generics.ListAPIView):
    serializer_class = EnrollmentSerializer

    def get_queryset(self):
        return Enrollment.objects.filter(user=self.request.user).select_related('course', 'course__instructor')


class MyCertificatesView(generics.ListAPIView):
    serializer_class = CertificateSerializer

    def get_queryset(self):
        return Certificate.objects.filter(user=self.request.user).select_related('course', 'user')


class VerifyCertificateView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            cert = Certificate.objects.select_related('course', 'user').get(token=token)
        except (Certificate.DoesNotExist, ValueError):
            return Response({'valid': False}, status=404)
        return Response({'valid': True, 'holder': cert.user.full_name, 'course': cert.course.title,
                         'issued_at': cert.issued_at})


class LessonResourceView(APIView):
    """Download a lesson attachment — only for people allowed to see the lesson."""
    permission_classes = [AllowAny]

    def get(self, request, pk):
        lesson = Lesson.objects.select_related('section__course').filter(pk=pk).first()
        if not lesson or not lesson.resource:
            raise Http404
        course = lesson.section.course
        if not can_manage_course(request.user, course):
            if course.status != Course.Status.PUBLISHED or not (
                    lesson.is_free_preview or can_access_course(request.user, course)):
                raise PermissionDenied('Enroll in this course to download this file.')
        return FileResponse(lesson.resource.open('rb'), as_attachment=True,
                            filename=os.path.basename(lesson.resource.name))
