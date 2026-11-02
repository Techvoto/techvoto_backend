from django.contrib import admin

from .models import Category, Certificate, Course, Enrollment, Lesson, Review, Section


class SectionInline(admin.TabularInline):
    model = Section
    extra = 0


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['title', 'instructor', 'status', 'price_kobo', 'created_at']
    list_filter = ['status', 'level', 'category']
    search_fields = ['title', 'instructor__email']
    inlines = [SectionInline]


admin.site.register([Category, Section, Lesson, Enrollment, Review, Certificate])
