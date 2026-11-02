from datetime import timedelta

import os

from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsInstructorOrAdmin, can_manage_course, is_admin
from apps.courses.models import Course, Enrollment
from apps.courses.services import add_xp, can_access_course, notify, update_progress
from .models import Assignment, Question, Quiz, QuizAttempt, Submission
from .serializers import (AssignmentSerializer, AttemptSerializer, GradeSerializer,
                          QuestionPublicSerializer, QuestionWriteSerializer, QuizSerializer,
                          SubmissionSerializer, SubmitSerializer)

QUIZ_PASS_XP = 50
GRACE = timedelta(seconds=30)


def _visible(model, user):
    """Authors see everything they own; others see only published items in courses they joined."""
    if is_admin(user):
        return model.objects.all()
    return model.objects.filter(
        Q(course__instructor=user) | Q(is_published=True, course__enrollments__user=user)).distinct()


class QuizViewSet(viewsets.ModelViewSet):
    serializer_class = QuizSerializer
    filterset_fields = ['course']

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy', 'questions'):
            return [IsInstructorOrAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        if self.action in ('update', 'partial_update', 'destroy', 'questions'):
            qs = Quiz.objects.select_related('course')
            return qs if is_admin(self.request.user) else qs.filter(course__instructor=self.request.user)
        return _visible(Quiz, self.request.user).select_related('course')

    @action(detail=True, methods=['get'])
    def questions(self, request, pk=None):
        """Authoring view, including correct answers. Owner/admin only (queryset enforces it)."""
        quiz = self.get_object()
        return Response(QuestionWriteSerializer(quiz.questions.prefetch_related('choices'), many=True,
                                                context={'request': request}).data)


    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        quiz = self.get_object()
        if not can_access_course(request.user, quiz.course):
            raise PermissionDenied('Enroll in the course first.')
        if not quiz.questions.exists():
            raise ValidationError('This quiz has no questions yet.')

        with transaction.atomic():
            # Lock the user's existing attempts for this quiz.
            existing = list(
                QuizAttempt.objects.select_for_update()
                .filter(quiz=quiz, user=request.user)
                .order_by('ordinal')
            )

            # Close an expired open attempt.
            open_attempt = next((a for a in existing if a.submitted_at is None), None)
            if open_attempt and quiz.time_limit_minutes:
                deadline = open_attempt.started_at + timedelta(
                    minutes=quiz.time_limit_minutes) + GRACE
                if timezone.now() > deadline:
                    open_attempt.submitted_at = timezone.now()
                    open_attempt.save(update_fields=['submitted_at'])
                    open_attempt = None

            if not open_attempt:
                used = sum(1 for a in existing if a.submitted_at is not None)
                if quiz.max_attempts and used >= quiz.max_attempts:
                    raise ValidationError('You have used all attempts for this quiz.')
                open_attempt = QuizAttempt.objects.create(
                    quiz=quiz, user=request.user, ordinal=used + 1,
                )

        return Response({
            'attempt': AttemptSerializer(open_attempt).data,
            'time_limit_minutes': quiz.time_limit_minutes,
            'questions': QuestionPublicSerializer(
                quiz.questions.prefetch_related('choices'), many=True).data,
        })

    @action(detail=True, methods=['get'])
    def attempts(self, request, pk=None):
        quiz = self.get_object()
        qs = quiz.attempts.filter(user=request.user, submitted_at__isnull=False)
        return Response(AttemptSerializer(qs, many=True).data)


class QuestionViewSet(viewsets.ModelViewSet):
    serializer_class = QuestionWriteSerializer
    permission_classes = [IsInstructorOrAdmin]
    filterset_fields = ['quiz']
    pagination_class = None

    def get_queryset(self):
        qs = Question.objects.select_related('quiz__course').prefetch_related('choices')
        return qs if is_admin(self.request.user) else qs.filter(quiz__course__instructor=self.request.user)




from datetime import timedelta
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

class QuizSubmitView(APIView):
    """
    POST {"answers": {"<question_id>": [<choice_id>, ...]}} — grading is always server-side.
    """
    @transaction.atomic
    def post(self, request, pk):
        # 1. Row lock & Fetch: Prevent double-submits, concurrent requests, or dual XP exploits
        attempt = get_object_or_404(
            QuizAttempt.objects.select_for_update().select_related('quiz__course'), 
            pk=pk, 
            user=request.user
        )
        quiz = attempt.quiz

        if attempt.submitted_at:
            raise ValidationError('This attempt was already submitted.')

        now = timezone.now()

        # 2. Strict Expiration Guard: Hard auto-fail if past the deadline + GRACE period
        if quiz.time_limit_minutes:
            deadline = attempt.started_at + timedelta(minutes=quiz.time_limit_minutes) + GRACE
            if now > deadline:
                attempt.submitted_at = now
                attempt.score_pct = 0
                attempt.passed = False
                attempt.answers = {}
                attempt.save(update_fields=['submitted_at', 'score_pct', 'passed', 'answers'])
                
                used = quiz.attempts.filter(user=request.user, submitted_at__isnull=False).count()
                return Response({
                    'score_pct': 0,
                    'passed': False,
                    'expired': True,
                    'pass_mark_pct': quiz.pass_mark_pct,
                    'attempts_remaining': None if not quiz.max_attempts else max(quiz.max_attempts - used, 0),
                    'results': [],
                    'xp_awarded': 0,
                })

        # 3. Payload Validation
        answers = request.data.get('answers') or {}
        if not isinstance(answers, dict):
            raise ValidationError({'answers': 'Expected an object of question_id -> [choice_ids].'})

        # 4. Grading Pipeline
        earned = total = 0
        detail = []
        correct_by_q = {}
        
        for q in quiz.questions.prefetch_related('choices'):
            correct = {c.id for c in q.choices.all() if c.is_correct}
            correct_by_q[q.id] = sorted(correct)
            
            raw = answers.get(str(q.id), [])
            raw = raw if isinstance(raw, (list, tuple)) else [raw]
            try:
                chosen = {int(x) for x in raw}
            except (TypeError, ValueError):
                chosen = set()
                
            ok = chosen == correct
            total += q.points
            earned += q.points if ok else 0
            detail.append({'question': q.id, 'correct': ok, 'explanation': q.explanation})

        score = round(earned / total * 100) if total else 0
        passed = score >= quiz.pass_mark_pct
        first_pass = passed and not QuizAttempt.objects.filter(quiz=quiz, user=request.user, passed=True).exists()

        # 5. Persist Metrics
        attempt.answers = answers
        attempt.score_pct, attempt.passed, attempt.submitted_at = score, passed, now
        attempt.save()

        # 6. Side Effects (Gamification & Progression)
        if first_pass:
            add_xp(request.user, QUIZ_PASS_XP)
            
        enrollment = Enrollment.objects.filter(user=request.user, course=quiz.course).first()
        if enrollment:
            update_progress(enrollment)  # may complete the course & issue the certificate

        # 7. Visibility & Leak Prevention
        used = quiz.attempts.filter(user=request.user, submitted_at__isnull=False).count()
        exhausted = bool(quiz.max_attempts and used >= quiz.max_attempts)
        reveal = passed or exhausted

        if reveal:
            for d in detail:
                d['correct_choice_ids'] = correct_by_q[d['question']]
        else:
            for d in detail:
                d.pop('explanation')

        return Response({
            'score_pct': score,
            'passed': passed,
            'expired': False,
            'pass_mark_pct': quiz.pass_mark_pct,
            'attempts_remaining': None if not quiz.max_attempts else max(quiz.max_attempts - used, 0),
            'results': detail,
            'xp_awarded': QUIZ_PASS_XP if first_pass else 0
        })


class AssignmentViewSet(viewsets.ModelViewSet):
    serializer_class = AssignmentSerializer
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    filterset_fields = ['course']

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy', 'submissions'):
            return [IsInstructorOrAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        if self.action in ('update', 'partial_update', 'destroy', 'submissions'):
            qs = Assignment.objects.select_related('course')
            return qs if is_admin(self.request.user) else qs.filter(course__instructor=self.request.user)
        return _visible(Assignment, self.request.user).select_related('course')

    @action(detail=True, methods=['get'])
    def submissions(self, request, pk=None):
        subs = self.get_object().submissions.select_related('student')
        return Response(SubmissionSerializer(subs, many=True, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        assignment = self.get_object()
        course = assignment.course
        if not Enrollment.objects.filter(user=request.user, course=course).exists():
            raise PermissionDenied('Only enrolled students can submit.')
        if not assignment.is_published:
            raise PermissionDenied('This assignment is not open.')
        now = timezone.now()
        late = bool(assignment.due_at and now > assignment.due_at)
        if late and not assignment.allow_late:
            raise ValidationError('The deadline has passed.')
        s = SubmitSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        sub = Submission.objects.filter(assignment=assignment, student=request.user).first()
        if sub and sub.graded_at:
            raise ValidationError('This submission has been graded and can no longer be changed.')
        if not sub:
            sub = Submission(assignment=assignment, student=request.user)
        sub.text = s.validated_data.get('text', sub.text)
        if 'file' in s.validated_data:
            sub.file = s.validated_data['file']
        sub.is_late = late
        sub.save()
        notify(course.instructor, f'New submission: {assignment.title}',
               f'{request.user.full_name} submitted work.', f'/instructor/courses/{course.slug}/assignments')
        return Response(SubmissionSerializer(sub, context={'request': request}).data, status=201)


class SubmissionGradeView(APIView):
    permission_classes = [IsInstructorOrAdmin]

    def post(self, request, pk):
        sub = get_object_or_404(Submission.objects.select_related('assignment__course', 'student'), pk=pk)
        if not can_manage_course(request.user, sub.assignment.course):
            raise PermissionDenied('Only the course instructor can grade this.')
        s = GradeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if s.validated_data['score'] > sub.assignment.max_score:
            raise ValidationError({'score': f'Maximum score is {sub.assignment.max_score}.'})
        sub.score = s.validated_data['score']
        sub.feedback = s.validated_data.get('feedback', '')
        sub.graded_by, sub.graded_at = request.user, timezone.now()
        sub.save()
        notify(sub.student, f'Graded: {sub.assignment.title}', f'Score {sub.score}/{sub.assignment.max_score}',
               f'/courses/{sub.assignment.course.slug}')
        return Response(SubmissionSerializer(sub, context={'request': request}).data)


class GradebookView(APIView):
    permission_classes = [IsInstructorOrAdmin]

    def get(self, request, slug):
        course = get_object_or_404(Course, slug=slug)
        if not can_manage_course(request.user, course):
            raise PermissionDenied()

        quizzes = list(course.quizzes.filter(is_published=True))
        assignments = list(course.assignments.filter(is_published=True))

        # One query for every enrollment + user.
        enrollments = list(
            course.enrollments.select_related('user').order_by('user__last_name')
        )
        student_ids = [e.user_id for e in enrollments]

        # One query for all best quiz scores.
        from django.db.models import Max
        best_scores = (
            QuizAttempt.objects
            .filter(quiz__in=quizzes, user_id__in=student_ids,
                    submitted_at__isnull=False)
            .values('quiz_id', 'user_id')
            .annotate(best=Max('score_pct'))
        )
        score_map = {(row['quiz_id'], row['user_id']): row['best'] for row in best_scores}

        # One query for all assignment scores.
        subs = (
            Submission.objects
            .filter(assignment__in=assignments, student_id__in=student_ids)
            .values('assignment_id', 'student_id', 'score')
        )
        sub_map = {(row['assignment_id'], row['student_id']): row['score'] for row in subs}

        rows = []
        for e in enrollments:
            rows.append({
                'student_id': e.user_id,
                'student': e.user.full_name,
                'email': e.user.email,
                'progress_pct': e.progress_pct,
                'completed': e.completed_at is not None,
                'quizzes': {q.id: score_map.get((q.id, e.user_id)) for q in quizzes},
                'assignments': {a.id: sub_map.get((a.id, e.user_id)) for a in assignments},
            })

        return Response({
            'quizzes': [{'id': q.id, 'title': q.title} for q in quizzes],
            'assignments': [
                {'id': a.id, 'title': a.title, 'max_score': a.max_score}
                for a in assignments
            ],
            'rows': rows,
        })

class SubmissionFileView(APIView):
    """Only the student who submitted, the course instructor, or an admin may download."""

    def get(self, request, pk):
        sub = get_object_or_404(Submission.objects.select_related('assignment__course'), pk=pk)
        if not sub.file:
            raise Http404
        if sub.student_id != request.user.id and not can_manage_course(request.user, sub.assignment.course):
            raise PermissionDenied()
        return FileResponse(sub.file.open('rb'), as_attachment=True, filename=os.path.basename(sub.file.name))
