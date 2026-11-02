"""Helpers for the test-suite."""
from apps.courses.models import Category, Course, Lesson, Section
from apps.users.models import User

PASSWORD = 'Str0ng-pass-928!'


def make_user(email, role='student', **kw):
    return User.objects.create_user(email=email, password=PASSWORD, first_name='Test', last_name=role.title(),
                                    role=role, **{'email_verified': True, **kw})


def make_course(instructor, price_kobo=0, published=True, lessons=1):
    cat, _ = Category.objects.get_or_create(name='Tech', slug='tech')
    course = Course.objects.create(instructor=instructor, category=cat, title='Intro', description='d',
                                   price_kobo=price_kobo, status='published' if published else 'draft')
    section = Section.objects.create(course=course, title='S1', order=1)
    made = [Lesson.objects.create(section=section, title=f'L{i}', order=i, kind='video',
                                  video_url='https://example.com/secret.mp4', content='SECRET BODY')
            for i in range(1, lessons + 1)]
    return course, made
