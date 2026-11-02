from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('notifications', views.NotificationViewSet, basename='notification')
router.register('announcements', views.AnnouncementViewSet, basename='announcement')
router.register('threads', views.ThreadViewSet, basename='thread')
urlpatterns = [path('', include(router.urls))]
