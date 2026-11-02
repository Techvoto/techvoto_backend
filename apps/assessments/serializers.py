from rest_framework import serializers

from apps.courses.serializers import validate_upload
from .models import Assignment, Choice, Question, Quiz, QuizAttempt, Submission

from django.db import transaction
from typing import Optional, Union

# ---------- Quiz: student-facing (never exposes is_correct) ----------
class ChoicePublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Choice
        fields = ['id', 'text']


class QuestionPublicSerializer(serializers.ModelSerializer):
    choices = ChoicePublicSerializer(many=True, read_only=True)

    class Meta:
        model = Question
        fields = ['id', 'prompt', 'kind', 'points', 'order', 'choices']


class QuizSerializer(serializers.ModelSerializer):
    question_count = serializers.SerializerMethodField()
    attempts_used = serializers.SerializerMethodField()
    best_score_pct = serializers.SerializerMethodField()

    # apps/assessments/serializers.py
    


    class Meta:
        model = Quiz
        fields = ['id', 'course', 'title', 'description', 'pass_mark_pct', 'time_limit_minutes',
                  'max_attempts', 'is_required', 'is_published', 'question_count', 'attempts_used',
                  'best_score_pct']
        read_only_fields = ['id', 'question_count', 'attempts_used', 'best_score_pct']

    def _mine(self, obj):
        u = self.context['request'].user
        return obj.attempts.filter(user=u, submitted_at__isnull=False) if u.is_authenticated else obj.attempts.none()

    def get_question_count(self, obj):
        return obj.questions.count()

    def get_attempts_used(self, obj):
        return self._mine(obj).count()

    def get_best_score_pct(self, obj):
        best = self._mine(obj).order_by('-score_pct').first()
        return best.score_pct if best else None

    def validate_course(self, course):
        from apps.core.permissions import can_manage_course
        if not can_manage_course(self.context['request'].user, course):
            raise serializers.ValidationError('You can only add quizzes to your own courses.')
        return course

    def validate_pass_mark_pct(self, v):
        if not 1 <= v <= 100:
            raise serializers.ValidationError('Pass mark must be between 1 and 100.')
        return v


# ---------- Quiz: instructor authoring (includes correct answers) ----------
class ChoiceWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Choice
        fields = ['id', 'text', 'is_correct']


class QuestionWriteSerializer(serializers.ModelSerializer):
    choices = ChoiceWriteSerializer(many=True)

    class Meta:
        model = Question
        fields = ['id', 'quiz', 'prompt', 'kind', 'points', 'order', 'explanation', 'choices']

    def validate_quiz(self, quiz):
        from apps.core.permissions import can_manage_course
        if not can_manage_course(self.context['request'].user, quiz.course):
            raise serializers.ValidationError('You can only edit your own quizzes.')
        return quiz

    def validate(self, data):
        choices = data.get('choices', [])
        kind = data.get('kind', getattr(self.instance, 'kind', 'single'))
        correct = sum(1 for c in choices if c.get('is_correct'))
        if len(choices) < 2:
            raise serializers.ValidationError({'choices': 'Provide at least two choices.'})
        if kind == 'single' and correct != 1:
            raise serializers.ValidationError({'choices': 'A single-answer question needs exactly one correct choice.'})
        if kind == 'multiple' and correct < 1:
            raise serializers.ValidationError({'choices': 'Mark at least one correct choice.'})
        return data

    def create(self, validated):
        choices = validated.pop('choices')
        q = Question.objects.create(**validated)
        Choice.objects.bulk_create([Choice(question=q, **c) for c in choices])
        return q



    @transaction.atomic
    def update(self, instance, validated):
        choices = validated.pop('choices', None)
        validated.pop('quiz', None)
        for k, v in validated.items():
            setattr(instance, k, v)
        instance.save()
        if choices is not None:
            instance.choices.all().delete()
            Choice.objects.bulk_create([Choice(question=instance, **c) for c in choices])
        return instance


class AttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuizAttempt
        fields = ['id', 'quiz', 'started_at', 'submitted_at', 'score_pct', 'passed']





    

# ---------- Assignments ----------
class AssignmentSerializer(serializers.ModelSerializer):
    my_submission = serializers.SerializerMethodField()

    class Meta:
        model = Assignment
        fields = ['id', 'course', 'title', 'instructions', 'due_at', 'max_score', 'allow_late',
                  'is_published', 'my_submission']

    def validate_course(self, course):
        from apps.core.permissions import can_manage_course
        if not can_manage_course(self.context['request'].user, course):
            raise serializers.ValidationError('You can only add assignments to your own courses.')
        return course

    def get_my_submission(self, obj):
        u = self.context['request'].user
        sub = obj.submissions.filter(student=u).first() if u.is_authenticated else None
        return SubmissionSerializer(sub, context=self.context).data if sub else None


class SubmissionSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.full_name', read_only=True)
    file = serializers.SerializerMethodField()

    def get_file(self, obj):
        if not obj.file:
            return None
        return self.context['request'].build_absolute_uri(f'/api/submissions/{obj.id}/file/')

    class Meta:
        model = Submission
        fields = ['id', 'assignment', 'student', 'student_name', 'text', 'file', 'submitted_at',
                  'is_late', 'score', 'feedback', 'graded_at']
        read_only_fields = fields


class SubmitSerializer(serializers.Serializer):
    text = serializers.CharField(required=False, allow_blank=True, max_length=20000)
    file = serializers.FileField(required=False)

    def validate_file(self, f):
        return validate_upload(f)

    def validate(self, data):
        if not data.get('text') and not data.get('file'):
            raise serializers.ValidationError('Provide text or a file.')
        return data


class GradeSerializer(serializers.Serializer):
    score = serializers.IntegerField(min_value=0)
    feedback = serializers.CharField(required=False, allow_blank=True, max_length=5000)
