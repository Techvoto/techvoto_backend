from django.utils import timezone
from rest_framework import serializers

from apps.core.permissions import can_manage_course
from apps.courses.services import can_access_course
from .models import Attendance, LiveClass
from .services import join_window_open


class LiveClassSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source='course.title', read_only=True)
    host_name = serializers.CharField(source='host.full_name', read_only=True)
    is_host = serializers.SerializerMethodField()
    can_join = serializers.SerializerMethodField()

    class Meta:
        model = LiveClass
        fields = ['id', 'course', 'course_title', 'host_name', 'title', 'description', 'starts_at',
                  'duration_minutes', 'status', 'recording_url', 'is_host', 'can_join']
        read_only_fields = ['id', 'status', 'host_name', 'course_title', 'is_host', 'can_join']

    def get_is_host(self, obj):
        return obj.host_id == self.context['request'].user.id

    def get_can_join(self, obj):
        u = self.context['request'].user
        if obj.status in ('cancelled', 'ended') or not can_access_course(u, obj.course):
            return False
        return can_manage_course(u, obj.course) or join_window_open(obj)

    def validate_course(self, course):
        if not can_manage_course(self.context['request'].user, course):
            raise serializers.ValidationError('You can only schedule classes for your own courses.')
        return course

    def validate_starts_at(self, value):
        if self.instance is None and value < timezone.now():
            raise serializers.ValidationError('Start time must be in the future.')
        return value

    def validate_duration_minutes(self, v):
        if not 5 <= v <= 480:
            raise serializers.ValidationError('Duration must be between 5 and 480 minutes.')
        return v


class AttendanceSerializer(serializers.ModelSerializer):
    student = serializers.CharField(source='user.full_name')
    email = serializers.CharField(source='user.email')

    class Meta:
        model = Attendance
        fields = ['student', 'email', 'first_joined_at', 'last_joined_at', 'join_count']
