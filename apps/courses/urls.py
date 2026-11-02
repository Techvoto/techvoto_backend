from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('categories', views.CategoryViewSet, basename='category')
router.register('courses', views.CourseViewSet, basename='course')
router.register('sections', views.SectionViewSet, basename='section')
router.register('lessons', views.LessonViewSet, basename='lesson')

urlpatterns = [
    path('enrollments/', views.MyEnrollmentsView.as_view()),
    path('certificates/', views.MyCertificatesView.as_view()),
    path('certificates/verify/<uuid:token>/', views.VerifyCertificateView.as_view()),
    path('lessons/<int:pk>/resource/', views.LessonResourceView.as_view()),
    path('', include(router.urls)),
]
