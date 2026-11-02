from rest_framework import serializers

from apps.users.serializers import PublicUserSerializer, UserSerializer
from apps.core.images import optimize_image
from .models import Category, Certificate, Course, Enrollment, Lesson, Review, Section
from .services import can_access_course

import magic
from pathlib import Path

MAX_UPLOAD = 25 * 1024 * 1024

ALLOWED_RESOURCE_EXT = {
    '.pdf', '.zip', '.doc', '.docx', '.ppt', '.pptx',
    '.xls', '.xlsx', '.txt', '.csv', '.png', '.jpg', '.jpeg',
}

# magic-byte signatures per allowed extension.
# If the detected type is not here, the upload is rejected.
ALLOWED_MIME = {
    '.pdf':  {'application/pdf'},
    '.zip':  {'application/zip', 'application/x-zip-compressed'},
    '.doc':  {'application/msword'},
    '.docx': {'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
              'application/zip'},
    '.ppt':  {'application/vnd.ms-powerpoint'},
    '.pptx': {'application/vnd.openxmlformats-officedocument.presentationml.presentation',
              'application/zip'},
    '.xls':  {'application/vnd.ms-excel'},
    '.xlsx': {'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
              'application/zip'},
    '.txt':  {'text/plain'},
    '.csv':  {'text/plain', 'text/csv', 'application/csv'},
    '.png':  {'image/png'},
    '.jpg':  {'image/jpeg'},
    '.jpeg': {'image/jpeg'},
}


def validate_upload(f, allowed=ALLOWED_RESOURCE_EXT, max_bytes=MAX_UPLOAD):
    if f is None:
        return f
    if f.size > max_bytes:
        raise serializers.ValidationError(f'File too large (max {max_bytes // (1024 * 1024)} MB).')

    ext = Path(f.name).suffix.lower()
    if ext not in allowed:
        raise serializers.ValidationError('This file type is not allowed.')

    # Magic-byte check: read the first 8KB and ask libmagic.
    f.seek(0)
    head = f.read(8192)
    f.seek(0)
    detected = magic.from_buffer(head, mime=True)
    expected = ALLOWED_MIME.get(ext)
    if not expected or detected not in expected:
        raise serializers.ValidationError(
            'The uploaded file does not match its extension.'
        )
    return f

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug']


class LessonOutlineSerializer(serializers.ModelSerializer):
    """Curriculum view: never includes content, video URL or files."""
    class Meta:
        model = Lesson
        fields = ['id', 'title', 'order', 'kind', 'duration_minutes', 'is_free_preview']


class SectionSerializer(serializers.ModelSerializer):
    lessons = LessonOutlineSerializer(many=True, read_only=True)

    class Meta:
        model = Section
        fields = ['id', 'title', 'order', 'lessons']


class LessonDetailSerializer(serializers.ModelSerializer):
    completed = serializers.SerializerMethodField()
    resource = serializers.SerializerMethodField()
    course_slug = serializers.CharField(source='section.course.slug', read_only=True)

    class Meta:
        model = Lesson
        fields = ['id', 'title', 'order', 'kind', 'content', 'video_url', 'resource', 'duration_minutes',
                  'is_free_preview', 'course_slug', 'completed']

    def get_resource(self, obj):
        if not obj.resource:
            return None
        return self.context['request'].build_absolute_uri(f'/api/lessons/{obj.id}/resource/')

    def get_completed(self, obj):
        user = self.context['request'].user
        return bool(user.is_authenticated and obj.progress.filter(enrollment__user=user).exists())


class LessonWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = ['id', 'section', 'title', 'order', 'kind', 'content', 'video_url', 'resource',
                  'duration_minutes', 'is_free_preview']

    def validate_resource(self, f):
        return validate_upload(f)

    def validate_section(self, section):
        from apps.core.permissions import can_manage_course
        if not can_manage_course(self.context['request'].user, section.course):
            raise serializers.ValidationError('You can only add lessons to your own courses.')
        return section


class SectionWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Section
        fields = ['id', 'course', 'title', 'order']

    def validate_course(self, course):
        from apps.core.permissions import can_manage_course
        if not can_manage_course(self.context['request'].user, course):
            raise serializers.ValidationError('You can only edit your own courses.')
        return course


class CourseListSerializer(serializers.ModelSerializer):
    instructor = PublicUserSerializer(read_only=True)
    category = CategorySerializer(read_only=True)
    avg_rating = serializers.SerializerMethodField()
    student_count = serializers.SerializerMethodField()
    lesson_count = serializers.SerializerMethodField()
    is_free = serializers.ReadOnlyField()
    price_naira = serializers.ReadOnlyField()

    class Meta:
        model = Course
        fields = ['id', 'title', 'slug', 'subtitle', 'description', 'thumbnail', 'level', 'status',
                  'price_kobo', 'price_naira', 'is_free', 'instructor', 'category',
                  'avg_rating', 'student_count', 'lesson_count', 'published_at']

    # Values come from queryset annotations (see CourseViewSet); fall back gracefully elsewhere.
    def get_avg_rating(self, obj):
        v = getattr(obj, 'avg_rating_a', None)
        return round(v, 2) if v else None

    def get_student_count(self, obj):
        return getattr(obj, 'student_count_a', None) if hasattr(obj, 'student_count_a') else obj.enrollments.count()

    def get_lesson_count(self, obj):
        return getattr(obj, 'lesson_count_a', None) if hasattr(obj, 'lesson_count_a') else \
            Lesson.objects.filter(section__course=obj).count()


class CourseDetailSerializer(CourseListSerializer):
    sections = SectionSerializer(many=True, read_only=True)
    is_enrolled = serializers.SerializerMethodField()
    progress_pct = serializers.SerializerMethodField()
    can_manage = serializers.SerializerMethodField()

    class Meta(CourseListSerializer.Meta):
        fields = CourseListSerializer.Meta.fields + ['sections', 'is_enrolled', 'progress_pct', 'can_manage']

    def _enrollment(self, obj):
        user = self.context['request'].user
        if not user.is_authenticated:
            return None
        return obj.enrollments.filter(user=user).first()

    def get_is_enrolled(self, obj):
        return can_access_course(self.context['request'].user, obj)

    def get_progress_pct(self, obj):
        e = self._enrollment(obj)
        return e.progress_pct if e else 0

    def get_can_manage(self, obj):
        from apps.core.permissions import can_manage_course
        return can_manage_course(self.context['request'].user, obj)


class CourseWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ['id', 'slug', 'title', 'subtitle', 'description', 'thumbnail', 'category', 'level',
                  'price_kobo', 'status']
        read_only_fields = ['id', 'slug']

    def validate_thumbnail(self, f):
        f = validate_upload(f, allowed={'.png', '.jpg', '.jpeg', '.webp'}, max_bytes=3 * 1024 * 1024)
        try:
            return optimize_image(f, max_size=(1600, 1000), quality=82)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate(self, data):
        status = data.get('status', getattr(self.instance, 'status', 'draft'))
        if status == Course.Status.PUBLISHED:
            if self.instance is None or not Lesson.objects.filter(section__course=self.instance).exists():
                raise serializers.ValidationError({'status': 'Add at least one lesson before publishing.'})
        return data


class EnrollmentCourseSerializer(serializers.ModelSerializer):
    instructor_name = serializers.CharField(source='instructor.full_name', read_only=True)

    class Meta:
        model = Course
        fields = ['id', 'title', 'slug', 'thumbnail', 'level', 'instructor_name']


class EnrollmentSerializer(serializers.ModelSerializer):
    course = EnrollmentCourseSerializer(read_only=True)
    next_lesson_id = serializers.SerializerMethodField()
    lesson_count = serializers.SerializerMethodField()

    class Meta:
        model = Enrollment
        fields = ['id', 'course', 'source', 'enrolled_at', 'progress_pct', 'completed_at',
                  'next_lesson_id', 'lesson_count']

    def get_lesson_count(self, obj):
        return Lesson.objects.filter(section__course=obj.course).count()

    def get_next_lesson_id(self, obj):
        done = obj.lesson_progress.values_list('lesson_id', flat=True)
        nxt = Lesson.objects.filter(section__course=obj.course).exclude(id__in=done) \
            .order_by('section__order', 'section_id', 'order', 'id').first()
        return nxt.id if nxt else None


class StudentProgressSerializer(serializers.ModelSerializer):
    student = serializers.SerializerMethodField()

    class Meta:
        model = Enrollment
        fields = ['id', 'student', 'source', 'enrolled_at', 'progress_pct', 'completed_at']

    def get_student(self, obj):
        return {'id': obj.user_id, 'full_name': obj.user.full_name, 'email': obj.user.email}


class ReviewSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.full_name', read_only=True)

    class Meta:
        model = Review
        fields = ['id', 'user_name', 'rating', 'comment', 'created_at']


class CertificateSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source='course.title', read_only=True)
    holder = serializers.CharField(source='user.full_name', read_only=True)

    class Meta:
        model = Certificate
        fields = ['id', 'token', 'course_title', 'holder', 'issued_at']
