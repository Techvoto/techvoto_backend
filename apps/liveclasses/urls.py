from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('live-classes', views.LiveClassViewSet, basename='live-class')
urlpatterns = [path('', include(router.urls))]
