from rest_framework import serializers

from apps.core.permissions import can_manage_course
from apps.courses.services import can_access_course
from .models import Announcement, Notification, Reply, Thread


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'title', 'body', 'link', 'is_read', 'created_at']
        read_only_fields = fields


class AnnouncementSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source='author.full_name', read_only=True)

    class Meta:
        model = Announcement
        fields = ['id', 'course', 'title', 'body', 'author_name', 'created_at']
        read_only_fields = ['id', 'author_name', 'created_at']

    def validate_course(self, course):
        if not can_manage_course(self.context['request'].user, course):
            raise serializers.ValidationError('Only the course instructor can post announcements.')
        return course


class ReplySerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source='author.full_name', read_only=True)
    author_role = serializers.CharField(source='author.role', read_only=True)

    class Meta:
        model = Reply
        fields = ['id', 'body', 'author_name', 'author_role', 'created_at']
        read_only_fields = ['id', 'author_name', 'author_role', 'created_at']


class ThreadSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source='author.full_name', read_only=True)
    reply_count = serializers.IntegerField(source='replies.count', read_only=True)

    class Meta:
        model = Thread
        fields = ['id', 'course', 'lesson', 'title', 'body', 'author_name', 'is_resolved', 'reply_count', 'created_at']
        read_only_fields = ['id', 'author_name', 'is_resolved', 'reply_count', 'created_at']

    def validate_course(self, course):
        if not can_access_course(self.context['request'].user, course):
            raise serializers.ValidationError('Enroll in the course to start a discussion.')
        return course

    def validate(self, data):
        lesson = data.get('lesson')
        if lesson and lesson.section.course_id != data['course'].id:
            raise serializers.ValidationError({'lesson': 'That lesson is not part of this course.'})
        return data
