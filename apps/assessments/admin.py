from django.contrib import admin

from .models import Assignment, Choice, Question, Quiz, QuizAttempt, Submission

admin.site.register([Quiz, Question, Choice, QuizAttempt, Assignment, Submission])
