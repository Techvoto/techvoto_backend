from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('apps.users.urls')),
    path('api/', include('apps.courses.urls')),
    path('api/', include('apps.assessments.urls')),
    path('api/', include('apps.liveclasses.urls')),
    path('api/payments/', include('apps.payments.urls')),
    path('api/', include('apps.engagement.urls')),
    path('api/', include('apps.support.urls')),
    path('api/', include('apps.core.urls')),
    # Public uploads only. Lesson files and submissions are NOT here: they are served by permission-checked views.
    re_path(r'^media/(?P<path>(?:avatars|course_thumbnails)/.+)$', serve, {'document_root': settings.MEDIA_ROOT}),
]

if settings.EXPOSE_API_DOCS:
    urlpatterns += [
        path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
        path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
        path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    ]
