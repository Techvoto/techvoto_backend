"""
python manage.py seed_data [--reset] [--force]

Fills every page of the portal with realistic demo data:
  users (admin, 3 instructors, 12 students), categories, 8 courses (7 published, 1 draft) with sections and
  lessons, enrollments + progress, reviews, quizzes (+attempts), assignments (+graded submissions),
  certificates, live classes (past / live now / upcoming) with attendance, announcements, discussion threads,
  notifications and Paystack-style payment records.

Passwords: SEED_PASSWORD env var, otherwise one random password is generated and printed once.
Refuses to run with DEBUG=False unless --force. --reset removes everything this command created first.
Video URLs are public YouTube placeholders; replace them with your own content.
"""
import os
import random
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.assessments.models import Assignment, Choice, Question, Quiz, QuizAttempt, Submission
from apps.courses.models import Category, Course, Enrollment, Lesson, LessonProgress, Review, Section
from apps.courses.services import notify, update_progress
from apps.engagement.models import Announcement, Reply, Thread
from apps.liveclasses.models import Attendance, LiveClass
from apps.payments.models import Payment, RefundRequest
from apps.support.models import ContactMessage
from apps.users.models import User

DOMAIN = '@example.com'
VIDEOS = ['https://www.youtube.com/watch?v=rfscVS0vtbw', 'https://www.youtube.com/watch?v=PkZNo7MFNFg',
          'https://www.youtube.com/watch?v=qz0aGYrrlhU']

INSTRUCTORS = [
    ('ada.okafor', 'Ada', 'Okafor', 'Senior software engineer and mentor with 10 years of experience building products across Lagos and London.'),
    ('chidi.eze', 'Chidi', 'Eze', 'Data and security consultant who teaches practical, job-ready skills.'),
    ('ngozi.adeyemi', 'Ngozi', 'Adeyemi', 'Product designer and growth marketer. Loves turning beginners into confident practitioners.'),
]
STUDENTS = ['Tunde Bello', 'Amaka Nwosu', 'Ibrahim Musa', 'Zainab Yusuf', 'Emeka Obi', 'Folake Adebayo',
            'Seun Ogunleye', 'Chiamaka Eze', 'Bola Ajayi', 'Hauwa Danjuma', 'Kelechi Anyanwu', 'Damilola Fashola']

CATEGORIES = ['Programming', 'Web Development', 'Data', 'Design', 'Business', 'Security']

# slug-less spec: title, category, instructor idx, level, naira price, status, subtitle, sections, quiz, assignment
COURSES = [
    dict(title='Python for Beginners', cat='Programming', teacher=0, level='beginner', naira=0, status='published',
         subtitle='Write your first real programs in a weekend.',
         sections={'Getting started': ['What is Python?', 'Installing Python and VS Code', 'Your first program'],
                   'Core building blocks': ['Variables and data types', 'Conditions and loops', 'Functions'],
                   'Working with data': ['Lists and dictionaries', 'Reading and writing files', 'Mini project: expense tracker']},
         quiz=[('Which function prints text to the screen?', ['print()', 'echo()', 'show()'], [0], 'print() is the built-in output function.'),
               ('Which of these is a valid variable name?', ['2cool', 'my_score', 'my-score'], [1], 'Names cannot start with a digit or contain hyphens.'),
               ('Which are Python collection types? (pick all)', ['list', 'dict', 'loop'], [0, 1], 'Lists and dictionaries store collections; a loop is control flow.')],
         assignment=('Expense tracker', 'Build a small program that stores expenses in a list of dictionaries and prints the total per category.')),
    dict(title='JavaScript Essentials', cat='Web Development', teacher=0, level='beginner', naira=15000, status='published',
         subtitle='The language of the web, from zero to interactive pages.',
         sections={'Foundations': ['How JavaScript runs in the browser', 'Variables, types and operators', 'Functions and scope'],
                   'Making pages interactive': ['The DOM', 'Events', 'Fetching data from an API'],
                   'Level up': ['Arrays and objects in depth', 'Async and await', 'Project: weather widget']},
         quiz=[('Which keyword declares a block-scoped variable that can be reassigned?', ['let', 'const', 'var'], [0], 'let is block scoped and reassignable; const cannot be reassigned.'),
               ('What does the fetch() function return?', ['A Promise', 'A string', 'An array'], [0], 'fetch returns a Promise that resolves to a Response.'),
               ('Which method adds an event handler?', ['addEventListener', 'attachClick', 'onEvent'], [0], 'addEventListener is the standard way.')],
         assignment=('Weather widget', 'Use a public weather API to display the current temperature for a city typed by the user.')),
    dict(title='Responsive Web Design with HTML & CSS', cat='Web Development', teacher=1, level='beginner', naira=0, status='published',
         subtitle='Build beautiful pages that work on every screen.',
         sections={'HTML that makes sense': ['Semantic HTML', 'Forms and accessibility'],
                   'CSS layouts': ['The box model', 'Flexbox', 'CSS Grid'],
                   'Responsive design': ['Media queries', 'Mobile-first workflow', 'Project: portfolio page']},
         quiz=[('Which CSS feature is best for one-dimensional layouts?', ['Flexbox', 'Float', 'Tables'], [0], 'Flexbox is designed for rows or columns.'),
               ('What does a mobile-first approach mean?', ['Start with small screens, then enhance', 'Design only for phones', 'Hide content on desktop'], [0], 'You write base styles for mobile and add media queries for larger screens.'),
               ('Which tag is semantic?', ['<nav>', '<div>', '<b>'], [0], '<nav> describes the purpose of its content.')],
         assignment=('Portfolio page', 'Create a responsive one-page portfolio with a header, about section, projects grid and contact form.')),
    dict(title='Data Analysis with Excel & SQL', cat='Data', teacher=1, level='intermediate', naira=20000, status='published',
         subtitle='Turn raw numbers into decisions.',
         sections={'Excel for analysts': ['Cleaning messy data', 'Formulas that matter', 'PivotTables and charts'],
                   'SQL fundamentals': ['SELECT and WHERE', 'JOINs', 'GROUP BY and aggregates'],
                   'Telling the story': ['Dashboards', 'Presenting insights']},
         quiz=[('Which SQL clause filters rows before grouping?', ['WHERE', 'HAVING', 'ORDER BY'], [0], 'WHERE filters rows; HAVING filters groups.'),
               ('Which function looks up a value in a table?', ['XLOOKUP', 'SUMIF', 'CONCAT'], [0], 'XLOOKUP finds matches in a range.'),
               ('A JOIN combines...', ['Rows from two tables', 'Columns into one', 'Databases'], [0], 'JOINs match rows from related tables.')],
         assignment=('Sales dashboard', 'Using the sample sales file, produce a one-page dashboard showing revenue by month and top 5 products.')),
    dict(title='UI/UX Design Fundamentals', cat='Design', teacher=2, level='beginner', naira=12500, status='published',
         subtitle='Design interfaces people love to use.',
         sections={'Think like a designer': ['What is UX?', 'Research and personas', 'User flows'],
                   'Visual design': ['Typography and colour', 'Layout and spacing', 'Components and design systems'],
                   'From idea to prototype': ['Wireframing', 'Prototyping in Figma', 'Usability testing']},
         quiz=[('Which comes first in the design process?', ['Research', 'Visual polish', 'Launch'], [0], 'Understand users before designing solutions.'),
               ('What is a wireframe?', ['A low-fidelity layout', 'A final design', 'A database'], [0], 'Wireframes show structure without visual detail.'),
               ('Good contrast improves...', ['Readability', 'File size', 'Load time'], [0], 'Contrast makes text easier to read.')],
         assignment=('Redesign an app screen', 'Pick a screen from an app you use, identify 3 usability problems and design an improved version.')),
    dict(title='Digital Marketing Basics', cat='Business', teacher=2, level='beginner', naira=0, status='published',
         subtitle='Reach customers online with confidence.',
         sections={'The landscape': ['Channels overview', 'Defining your audience'],
                   'Core channels': ['Social media marketing', 'Email marketing', 'Search engine basics'],
                   'Measure and improve': ['Analytics 101', 'Running your first campaign']},
         quiz=[('What does CTR stand for?', ['Click-through rate', 'Cost to reach', 'Customer retention rate'], [0], 'CTR = clicks divided by impressions.'),
               ('Which metric measures cost of getting a customer?', ['CAC', 'ROI', 'CTR'], [0], 'Customer acquisition cost.'),
               ('Email lists should be built with...', ['Permission', 'Purchased lists', 'Scraping'], [0], 'Permission-based lists protect deliverability and trust.')],
         assignment=('Campaign plan', 'Write a one-page plan for promoting a small business: audience, channels, budget and success metrics.')),
    dict(title='Cybersecurity Essentials', cat='Security', teacher=1, level='intermediate', naira=25000, status='published',
         subtitle='Protect people, data and systems from common attacks.',
         sections={'Foundations': ['The CIA triad', 'Threats and attackers', 'Passwords and authentication'],
                   'Defending systems': ['Network security basics', 'Web application security', 'Encryption in practice'],
                   'Responding': ['Incident response', 'Building a security culture']},
         quiz=[('What does the "C" in the CIA triad stand for?', ['Confidentiality', 'Cryptography', 'Compliance'], [0], 'Confidentiality, Integrity, Availability.'),
               ('Which is a strong authentication practice?', ['Multi-factor authentication', 'Reusing passwords', 'Sharing codes'], [0], 'MFA adds a second proof of identity.'),
               ('Phishing is an example of...', ['Social engineering', 'Brute force', 'Denial of service'], [0], 'Phishing manipulates people into giving access.')],
         assignment=('Security audit', 'Review a small website or app of your choice and list 5 risks with recommended fixes.')),
    dict(title='Intro to Machine Learning', cat='Data', teacher=0, level='advanced', naira=30000, status='draft',
         subtitle='Coming soon: models, data and evaluation.',
         sections={'Foundations': ['What is machine learning?', 'Data preparation'],
                   'Models': ['Regression', 'Classification']},
         quiz=None, assignment=None),
]

THREADS = [
    ('I keep getting an error when running my code. Any tips?', 'My program stops with a syntax error and I cannot see why. What is the best way to debug this?',
     ['Read the last line of the error message first: it tells you the file, the line and the type of problem. Then check for missing colons, brackets or quotes.',
      'Thank you, that fixed it. I had a missing bracket!']),
    ('What should I focus on if I only have 30 minutes a day?', 'I work full time and can only study briefly. How would you prioritise the lessons?',
     ['Do one lesson per day and finish the small exercise at the end. Consistency beats long, irregular sessions.']),
    ('Can we get more practice projects?', 'The lessons are great. Could we have an extra project to practise with?', []),
]


def lesson_md(title, course):
    return (f'## {title}\n\nWelcome to this lesson of **{course}**. By the end you will be able to explain the idea in your '
            f'own words and apply it in a small exercise.\n\n### Key ideas\n\n- Start with the big picture, then zoom in on details.\n'
            f'- Practise as you go: reading alone is not enough.\n- Take notes and revisit them tomorrow.\n\n'
            f'### Try it yourself\n\n```text\nStep 1: read the example\nStep 2: change one thing\nStep 3: predict the result, then check\n```\n\n'
            f'> **Tip:** if you get stuck, post a question in the course discussion and your instructor will help.\n')


class Command(BaseCommand):
    help = 'Seed demo data for every page of the portal'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Delete previously seeded demo data first')
        parser.add_argument('--force', action='store_true', help='Allow running when DEBUG=False')

    @transaction.atomic
    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts['force']:
            raise CommandError('Refusing to seed with DEBUG=False. Use --force if you really mean it.')
        self.rng = random.Random(42)
        self.password = os.environ.get('SEED_PASSWORD') or secrets.token_urlsafe(10)
        self.created_accounts = []
        if opts['reset']:
            self.reset()

        admin = self.user('admin', 'Site', 'Admin', 'admin', bio='Platform administrator.')
        teachers = [self.user(h, f, l, 'instructor', bio=b) for h, f, l, b in INSTRUCTORS]
        students = []
        for i, full in enumerate(STUDENTS):
            f, l = full.split(' ', 1)
            students.append(self.user(f'{f}.{l}'.lower(), f, l, 'student', xp=self.rng.randint(40, 1800),
                                      streak=self.rng.randint(0, 14)))

        cats = {n: Category.objects.get_or_create(name=n, defaults={'slug': n.lower().replace(' ', '-')})[0] for n in CATEGORIES}
        courses = []
        for spec in COURSES:
            course = self.course(spec, cats, teachers)
            if course:
                courses.append((course, spec))

        published = [(c, s) for c, s in courses if c.status == 'published']
        for course, spec in published:
            self.enrollments(course, students)
            self.reviews(course)
            self.assignments(course, spec)
            self.announcement(course)
            self.threads(course, students)
            self.live_classes(course, students)
        self.notifications(students)
        self.support_data()

        self.stdout.write(self.style.SUCCESS(f'Seeded {len(courses)} new course(s).'))
        if self.created_accounts:
            self.stdout.write(f'\nPassword for all newly created demo accounts: {self.password}')
            for email, role in self.created_accounts:
                self.stdout.write(f'  {role:<11} {email}')
            self.stdout.write('Store the password now; it is not shown again.')
        else:
            self.stdout.write('All demo accounts already existed (their passwords are unchanged).')

    # ------------------------------------------------------------------ helpers
    def reset(self):
        self.stdout.write('Removing previously seeded data...')
        ContactMessage.objects.filter(email__endswith=DOMAIN).delete()
        Payment.objects.filter(user__email__endswith=DOMAIN).delete()
        Course.objects.filter(instructor__email__endswith=DOMAIN).delete()
        Category.objects.filter(name__in=CATEGORIES, courses__isnull=True).delete()
        User.objects.filter(email__endswith=DOMAIN, is_superuser=False).delete()
        User.objects.filter(email='admin' + DOMAIN).delete()

    def user(self, handle, first, last, role, **extra):
        email = f'{handle}{DOMAIN}'
        user = User.objects.filter(email=email).first()
        if user:
            return user
        make = User.objects.create_superuser if role == 'admin' else User.objects.create_user
        user = make(email=email, password=self.password, first_name=first, last_name=last, role=role,
                    email_verified=True, **extra)
        self.created_accounts.append((email, role))
        return user

    def course(self, spec, cats, teachers):
        if Course.objects.filter(title=spec['title']).exists():
            return None
        c = Course.objects.create(
            instructor=teachers[spec['teacher']], category=cats[spec['cat']], title=spec['title'],
            subtitle=spec['subtitle'], level=spec['level'], price_kobo=spec['naira'] * 100, status='draft',
            description=f"{spec['subtitle']}\n\nThis course combines short video lessons, readings, quizzes and a hands-on "
                        f"project so you learn by doing. No prior experience needed unless stated in the level.")
        n = 0
        for si, (sec_title, lessons) in enumerate(spec['sections'].items(), start=1):
            section = Section.objects.create(course=c, title=sec_title, order=si)
            for li, title in enumerate(lessons, start=1):
                n += 1
                Lesson.objects.create(section=section, title=title, order=li, kind='video' if n % 3 else 'text',
                                      content=lesson_md(title, c.title), video_url=VIDEOS[n % 3] if n % 3 else '',
                                      duration_minutes=self.rng.choice([6, 8, 10, 12, 15]), is_free_preview=(n == 1))
        if spec['quiz']:
            quiz = Quiz.objects.create(course=c, title='Knowledge check', description='Check what you have learned so far.',
                                       pass_mark_pct=60, time_limit_minutes=15, max_attempts=3, is_required=True, is_published=True)
            for qi, (prompt, choices, correct, why) in enumerate(spec['quiz'], start=1):
                q = Question.objects.create(quiz=quiz, prompt=prompt, order=qi, explanation=why,
                                            kind='multiple' if len(correct) > 1 else 'single')
                for ci, text in enumerate(choices):
                    Choice.objects.create(question=q, text=text, is_correct=ci in correct)
        c.status = spec['status']
        c.save()
        return c

    def enrollments(self, course, students):
        quiz = course.quizzes.first()
        lessons = list(Lesson.objects.filter(section__course=course).order_by('section__order', 'order'))
        takers = self.rng.sample(students, k=self.rng.randint(6, len(students)))
        for student in takers:
            paid = course.price_kobo > 0
            e, created = Enrollment.objects.get_or_create(user=student, course=course,
                                                           defaults={'source': 'paid' if paid else 'free'})
            if not created:
                continue
            if paid:
                Payment.objects.create(user=student, course=course, reference=f'seed_{secrets.token_hex(10)}',
                                       amount_kobo=course.price_kobo, status='success', paid_at=timezone.now() - timedelta(days=self.rng.randint(1, 60)),
                                       gateway_response={'status': 'success', 'channel': 'card'})
            fraction = self.rng.choice([0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.0])
            done = round(len(lessons) * fraction)
            for lesson in lessons[:done]:
                LessonProgress.objects.get_or_create(enrollment=e, lesson=lesson)
            if quiz and fraction >= 0.6:
                score = self.rng.choice([67, 100, 100]) if fraction == 1.0 else self.rng.choice([33, 67, 100])
                QuizAttempt.objects.create(quiz=quiz, user=student, submitted_at=timezone.now() - timedelta(days=self.rng.randint(0, 20)),
                                           score_pct=score, passed=score >= quiz.pass_mark_pct)
            if fraction == 1.0 and quiz and not QuizAttempt.objects.filter(quiz=quiz, user=student, passed=True).exists():
                QuizAttempt.objects.create(quiz=quiz, user=student, submitted_at=timezone.now(), score_pct=100, passed=True)
            update_progress(e)   # computes %, and issues the certificate when truly complete

    def reviews(self, course):
        comments = ['Clear explanations and great pacing.', 'Exactly what I needed to get started.',
                    'The project at the end made everything click.', 'Good course, would love more advanced material.',
                    'Instructor answers questions quickly. Highly recommended!']
        enrolled = list(course.enrollments.select_related('user').order_by('?')[:5])
        for e in enrolled:
            Review.objects.get_or_create(course=course, user=e.user,
                                         defaults={'rating': self.rng.choice([4, 4, 5, 5, 5, 3]), 'comment': self.rng.choice(comments)})

    def assignments(self, course, spec):
        if not spec['assignment']:
            return
        title, instructions = spec['assignment']
        a = Assignment.objects.create(course=course, title=title, instructions=instructions, is_published=True,
                                      due_at=timezone.now() + timedelta(days=self.rng.randint(5, 21)), max_score=100)
        for e in course.enrollments.select_related('user').filter(progress_pct__gte=40)[:6]:
            graded = self.rng.random() < 0.6
            Submission.objects.create(
                assignment=a, student=e.user, is_late=False,
                text='Here is my submission. I followed the instructions and added comments to explain my approach.',
                score=self.rng.randint(55, 98) if graded else None,
                feedback='Well structured. Next time, add tests for edge cases.' if graded else '',
                graded_by=course.instructor if graded else None, graded_at=timezone.now() if graded else None)

    def announcement(self, course):
        Announcement.objects.create(course=course, author=course.instructor, title='Welcome to the course!',
                                    body=f'Hi everyone, welcome to {course.title}. Start with the first section, join the live '
                                         f'classes and ask questions in the discussion tab. Happy learning!')

    def threads(self, course, students):
        enrolled = list(course.enrollments.select_related('user')[:6])
        if len(enrolled) < 2:
            return
        for (title, body, replies), e in zip(THREADS, enrolled):
            t = Thread.objects.create(course=course, author=e.user, title=title, body=body, is_resolved=bool(replies))
            for i, text in enumerate(replies):
                Reply.objects.create(thread=t, author=course.instructor if i == 0 else e.user, body=text)

    def live_classes(self, course, students):
        now = timezone.now()
        plan = [('Kick-off and Q&A', -timedelta(days=9), 'ended'), ('Hands-on workshop', -timedelta(days=3), 'ended'),
                ('Office hours', timedelta(days=2, hours=1), 'scheduled'), ('Project review', timedelta(days=7), 'scheduled')]
        if course.title in ('Python for Beginners', 'Responsive Web Design with HTML & CSS'):
            plan.append(('Live coding session (happening now)', -timedelta(minutes=5), 'live'))
        for title, delta, status in plan:
            live = LiveClass.objects.create(course=course, host=course.instructor, title=title, starts_at=now + delta,
                                            duration_minutes=60, status=status,
                                            description='Bring your questions. The session is interactive.')
            if status == 'ended':
                for e in course.enrollments.select_related('user').order_by('?')[:self.rng.randint(3, 6)]:
                    Attendance.objects.get_or_create(live_class=live, user=e.user, defaults={'join_count': self.rng.randint(1, 2)})

    def notifications(self, students):
        for s in students[:4]:
            notify(s, 'Welcome to Techvoto', 'Browse the catalogue and start your first course.', '/courses')
        main = students[0]
        notify(main, 'New live class scheduled', 'Office hours is coming up soon.', '/live')

    def support_data(self):
        """A pending refund request (low progress, recent payment) and a few contact-form messages."""
        for p in Payment.objects.filter(user__email__endswith=DOMAIN, status='success', refund_request__isnull=True):
            e = Enrollment.objects.filter(user=p.user, course=p.course).first()
            if e and e.progress_pct <= 30:
                Payment.objects.filter(pk=p.pk).update(paid_at=timezone.now() - timedelta(days=1))   # inside the refund window
                RefundRequest.objects.create(payment=p, user=p.user, reason='I enrolled by mistake and chose the wrong course for my level.')
                break
        if not ContactMessage.objects.filter(email__endswith=DOMAIN).exists():
            for name, subject, msg in [
                ('Kemi Adeola', 'Corporate training enquiry', 'We would like to train 25 staff members. Do you offer team plans?'),
                ('Yusuf Garba', 'Certificate not showing', 'I finished the course but cannot see my certificate yet.'),
                ('Ify Okeke', 'Partnership', 'I run a coding bootcamp and would love to explore a partnership.')]:
                ContactMessage.objects.create(name=name, email=f'{name.split()[0].lower()}{DOMAIN}', subject=subject, message=msg)
