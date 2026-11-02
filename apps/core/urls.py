from django.urls import path

from . import views

urlpatterns = [
    path('health/', views.HealthView.as_view()),
    path('search/', views.SearchView.as_view()),
    path('stats/admin/', views.AdminStatsView.as_view()),
    path('stats/instructor/', views.InstructorStatsView.as_view()),
]
