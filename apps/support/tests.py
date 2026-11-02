from django.core import mail
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.testing import make_user
from .models import ContactMessage

PAYLOAD = {'name': 'Ada', 'email': 'ada@x.com', 'subject': 'Help', 'message': 'I cannot access my course.'}


class ContactTests(TestCase):
    def setUp(self):
        self.c = APIClient()

    def test_anyone_can_send_and_team_is_emailed(self):
        r = self.c.post('/api/contact/', PAYLOAD, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(ContactMessage.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_honeypot_discards_silently(self):
        r = self.c.post('/api/contact/', {**PAYLOAD, 'website': 'http://spam.example'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_inbox_is_admin_only(self):
        ContactMessage.objects.create(**PAYLOAD)
        self.c.force_authenticate(make_user('s@x.com'))
        self.assertEqual(self.c.get('/api/contact/messages/').status_code, 403)
        self.c.force_authenticate(make_user('a@x.com', 'admin'))
        r = self.c.get('/api/contact/messages/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['count'], 1)
        mid = r.data['results'][0]['id']
        self.assertEqual(self.c.patch(f'/api/contact/messages/{mid}/', {'is_handled': True}, format='json').status_code, 200)
