from django.db.models import Q
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsInstructorOrAdmin, can_manage_course, is_admin
from apps.courses.services import can_access_course, notify
from .models import Announcement, Notification, Thread
from .serializers import (AnnouncementSerializer, NotificationSerializer, ReplySerializer, ThreadSerializer)


def _course_scope(user):
    """Filter for objects whose `course` the user may see (enrolled or teaching)."""
    return Q() if is_admin(user) else Q(course__instructor=user) | Q(course__enrollments__user=user)


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=True, methods=['post'])
    def read(self, request, pk=None):
        n = self.get_queryset().filter(pk=pk).first()
        if n:
            n.is_read = True
            n.save(update_fields=['is_read'])
        return Response({'ok': True})

    @action(detail=False, methods=['post'], url_path='read-all')
    def read_all(self, request):
        self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({'ok': True})

    @action(detail=False, methods=['get'], url_path='unread-count')
    def unread_count(self, request):
        return Response({'count': self.get_queryset().filter(is_read=False).count()})


class AnnouncementViewSet(viewsets.ModelViewSet):
    serializer_class = AnnouncementSerializer
    filterset_fields = ['course']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_permissions(self):
        from rest_framework.permissions import IsAuthenticated
        return [IsInstructorOrAdmin()] if self.action in ('create', 'destroy') else [IsAuthenticated()]

    def get_queryset(self):
        qs = Announcement.objects.select_related('author', 'course')
        if self.action == 'destroy':
            return qs if is_admin(self.request.user) else qs.filter(course__instructor=self.request.user)
        return qs.filter(_course_scope(self.request.user)).distinct()

    def perform_create(self, serializer):
        a = serializer.save(author=self.request.user)
        for e in a.course.enrollments.select_related('user'):
            notify(e.user, f'{a.course.title}: {a.title}', a.body[:140], f'/courses/{a.course.slug}')


class ThreadViewSet(viewsets.ModelViewSet):
    serializer_class = ThreadSerializer
    filterset_fields = ['course', 'lesson']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = Thread.objects.select_related('author', 'course').prefetch_related('replies')
        qs = qs.filter(_course_scope(self.request.user)).distinct()
        if self.action == 'destroy':
            u = self.request.user
            qs = qs if is_admin(u) else qs.filter(Q(author=u) | Q(course__instructor=u))
        return qs

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    @action(detail=True, methods=['get', 'post'])
    def replies(self, request, pk=None):
        thread = self.get_object()
        if request.method == 'GET':
            return Response(ReplySerializer(thread.replies.select_related('author'), many=True).data)
        s = ReplySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        reply = s.save(thread=thread, author=request.user)
        if thread.author_id != request.user.id:
            notify(thread.author, f'New reply: {thread.title}', reply.body[:140], f'/courses/{thread.course.slug}/discussion')
        return Response(ReplySerializer(reply).data, status=201)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        thread = self.get_object()
        if thread.author_id != request.user.id and not can_manage_course(request.user, thread.course):
            raise PermissionDenied()
        thread.is_resolved = not thread.is_resolved
        thread.save(update_fields=['is_resolved'])
        return Response({'is_resolved': thread.is_resolved})
