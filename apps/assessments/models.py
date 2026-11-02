from django.conf import settings
from django.db import models


class Quiz(models.Model):
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='quizzes')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    pass_mark_pct = models.PositiveSmallIntegerField(default=70)
    time_limit_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    max_attempts = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Blank = unlimited')
    is_required = models.BooleanField(default=False, help_text='Must be passed to earn the certificate')
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'quizzes'
        ordering = ['created_at']

    def __str__(self):
        return self.title


class Question(models.Model):
    class Kind(models.TextChoices):
        SINGLE = 'single', 'Single answer'
        MULTIPLE = 'multiple', 'Multiple answers'

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='questions')
    prompt = models.TextField()
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SINGLE)
    points = models.PositiveSmallIntegerField(default=1)
    order = models.PositiveSmallIntegerField(default=0)
    explanation = models.TextField(blank=True)

    class Meta:
        ordering = ['order', 'id']


class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choices')
    text = models.CharField(max_length=500)
    is_correct = models.BooleanField(default=False)

    class Meta:
        ordering = ['id']


class QuizAttempt(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='attempts')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='quiz_attempts')
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    score_pct = models.PositiveSmallIntegerField(default=0)
    passed = models.BooleanField(default=False)
    answers = models.JSONField(default=dict, blank=True)
    ordinal = models.PositiveSmallIntegerField(default=1)  

    class Meta:
        ordering = ['-started_at']
        constraints = [
            models.UniqueConstraint(
                fields=['quiz', 'user', 'ordinal'],
                name='uniq_quizattempt_ordinal_per_user',
            ),
        ]


class Assignment(models.Model):
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='assignments')
    title = models.CharField(max_length=200)
    instructions = models.TextField()
    due_at = models.DateTimeField(null=True, blank=True)
    max_score = models.PositiveSmallIntegerField(default=100)
    allow_late = models.BooleanField(default=False)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['due_at', 'created_at']

    def __str__(self):
        return self.title


class Submission(models.Model):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name='submissions')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='submissions')
    text = models.TextField(blank=True)
    file = models.FileField(upload_to='submissions/', blank=True, null=True)
    submitted_at = models.DateTimeField(auto_now=True)
    is_late = models.BooleanField(default=False)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    feedback = models.TextField(blank=True)
    graded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='graded_submissions')
    graded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ['assignment', 'student']
        ordering = ['-submitted_at']
