from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('contact/messages', views.AdminContactViewSet, basename='contact-message')

urlpatterns = [
    path('contact/', views.ContactCreateView.as_view()),
    path('', include(router.urls)),
]
