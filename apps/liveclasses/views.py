from datetime import timedelta

from django.db.models import F, Q
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsInstructorOrAdmin, can_manage_course, is_admin
from apps.courses.services import can_access_course, notify
from .models import Attendance, LiveClass
from .serializers import AttendanceSerializer, LiveClassSerializer
from .services import jitsi_connection, join_window_open


class LiveClassViewSet(viewsets.ModelViewSet):
    serializer_class = LiveClassSerializer
    filterset_fields = ['course', 'status']
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = ['starts_at']
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy', 'end', 'cancel', 'attendance'):
            return [IsInstructorOrAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        qs = LiveClass.objects.select_related('course', 'host')
        if self.action in ('update', 'partial_update', 'destroy', 'end', 'cancel', 'attendance'):
            return qs if is_admin(user) else qs.filter(course__instructor=user)
        if not is_admin(user):
            qs = qs.filter(Q(course__instructor=user) | Q(course__enrollments__user=user)).distinct()
        if self.request.query_params.get('upcoming'):
            qs = qs.filter(starts_at__gte=timezone.now() - timedelta(hours=3)).exclude(
                status__in=['cancelled', 'ended'])
        return qs

    def perform_create(self, serializer):
        live = serializer.save(host=self.request.user)
        for student in live.course.enrollments.select_related('user'):
            notify(student.user, f'Live class scheduled: {live.title}',
                   live.starts_at.strftime('%a %d %b, %H:%M'), '/live')

    @action(detail=True, methods=['post'])
    def join(self, request, pk=None):
        live = self.get_object()
        if live.status in ('cancelled', 'ended'):
            raise ValidationError('This class is no longer available.')
        if not can_access_course(request.user, live.course):
            raise PermissionDenied('Enroll in the course to join its live classes.')
        is_mod = can_manage_course(request.user, live.course)
        if not is_mod and not join_window_open(live):
            raise ValidationError('The class is not open yet. You can join 15 minutes before it starts.')
        if is_mod and live.status == LiveClass.Status.SCHEDULED:
            live.status = LiveClass.Status.LIVE
            live.save(update_fields=['status'])
        elif not is_mod and live.status == LiveClass.Status.SCHEDULED:
            # Students can wait in the room; the host starts it.
            pass
        if not is_mod:
            att, created = Attendance.objects.get_or_create(live_class=live, user=request.user)
            if not created:
                Attendance.objects.filter(pk=att.pk).update(join_count=F('join_count') + 1,
                                                            last_joined_at=timezone.now())
        return Response(jitsi_connection(request.user, live, is_mod))

    @action(detail=True, methods=['post'])
    def end(self, request, pk=None):
        live = self.get_object()
        live.status = LiveClass.Status.ENDED
        live.save(update_fields=['status'])
        return Response(self.get_serializer(live).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        live = self.get_object()
        if live.status == LiveClass.Status.ENDED:
            raise ValidationError('Ended classes cannot be cancelled.')
        live.status = LiveClass.Status.CANCELLED
        live.save(update_fields=['status'])
        for e in live.course.enrollments.select_related('user'):
            notify(e.user, f'Class cancelled: {live.title}', link='/live')
        return Response(self.get_serializer(live).data)

    @action(detail=True, methods=['get'])
    def attendance(self, request, pk=None):
        live = self.get_object()
        return Response(AttendanceSerializer(live.attendance.select_related('user'), many=True).data)
