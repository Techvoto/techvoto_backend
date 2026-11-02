import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify


class Category(models.Model):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(unique=True)

    class Meta:
        verbose_name_plural = 'categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class Course(models.Model):
    class Level(models.TextChoices):
        BEGINNER = 'beginner', 'Beginner'
        INTERMEDIATE = 'intermediate', 'Intermediate'
        ADVANCED = 'advanced', 'Advanced'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PUBLISHED = 'published', 'Published'
        ARCHIVED = 'archived', 'Archived'

    instructor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='taught_courses')
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='courses')
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, blank=True)
    subtitle = models.CharField(max_length=250, blank=True)
    description = models.TextField(blank=True)
    thumbnail = models.ImageField(upload_to='course_thumbnails/', blank=True, null=True)
    level = models.CharField(max_length=20, choices=Level.choices, default=Level.BEGINNER)
    price_kobo = models.PositiveIntegerField(default=0, help_text='Price in kobo (₦1 = 100 kobo). 0 means free.')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    @property
    def is_free(self):
        return self.price_kobo == 0

    @property
    def price_naira(self):
        return self.price_kobo / 100

    def save(self, *args, **kwargs):
        from django.utils import timezone
        if not self.slug:
            base = slugify(self.title)[:180] or 'course'
            slug, n = base, 1
            while Course.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                n += 1
                slug = f'{base}-{n}'
            self.slug = slug
        if self.status == self.Status.PUBLISHED and not self.published_at:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)


class Section(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='sections')
    title = models.CharField(max_length=200)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f'{self.course.title} / {self.title}'


class Lesson(models.Model):
    class Kind(models.TextChoices):
        VIDEO = 'video', 'Video'
        TEXT = 'text', 'Reading'
        FILE = 'file', 'Downloadable file'

    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='lessons')
    title = models.CharField(max_length=200)
    order = models.PositiveSmallIntegerField(default=0)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.VIDEO)
    content = models.TextField(blank=True, help_text='Markdown / rich text body')
    video_url = models.URLField(blank=True)
    resource = models.FileField(upload_to='lesson_resources/', blank=True, null=True)
    duration_minutes = models.PositiveSmallIntegerField(default=0)
    is_free_preview = models.BooleanField(default=False)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.title

    @property
    def course(self):
        return self.section.course


class Enrollment(models.Model):
    class Source(models.TextChoices):
        FREE = 'free', 'Free'
        PAID = 'paid', 'Paid'
        ADMIN = 'admin', 'Admin'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='enrollments')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrollments')
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.FREE)
    enrolled_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    progress_pct = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ['user', 'course']
        ordering = ['-enrolled_at']


class LessonProgress(models.Model):
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name='lesson_progress')
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='progress')
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['enrollment', 'lesson']


class Review(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(blank=True, max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['course', 'user']
        ordering = ['-created_at']


class Certificate(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='certificates')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='certificates')
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'course']
        ordering = ['-issued_at']
