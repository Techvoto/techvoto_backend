from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('quizzes', views.QuizViewSet, basename='quiz')
router.register('questions', views.QuestionViewSet, basename='question')
router.register('assignments', views.AssignmentViewSet, basename='assignment')

urlpatterns = [
    path('attempts/<int:pk>/submit/', views.QuizSubmitView.as_view()),
    path('submissions/<int:pk>/file/', views.SubmissionFileView.as_view()),
    path('submissions/<int:pk>/grade/', views.SubmissionGradeView.as_view()),
    path('courses/<slug:slug>/gradebook/', views.GradebookView.as_view()),
    path('', include(router.urls)),
]
