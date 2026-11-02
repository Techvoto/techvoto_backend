import secrets

from django.conf import settings
from django.db import models


def new_room_name():
    # Unguessable: the room name is the only thing standing between strangers and a class on public Jitsi.
    return 'tv-' + secrets.token_urlsafe(18).replace('_', 'x')


class LiveClass(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = 'scheduled', 'Scheduled'
        LIVE = 'live', 'Live'
        ENDED = 'ended', 'Ended'
        CANCELLED = 'cancelled', 'Cancelled'

    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='live_classes')
    host = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='hosted_classes')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField(db_index=True)
    duration_minutes = models.PositiveSmallIntegerField(default=60)
    room_name = models.CharField(max_length=64, unique=True, default=new_room_name, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED, db_index=True)
    recording_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['starts_at']

    def __str__(self):
        return self.title


class Attendance(models.Model):
    live_class = models.ForeignKey(LiveClass, on_delete=models.CASCADE, related_name='attendance')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='attendance')
    first_joined_at = models.DateTimeField(auto_now_add=True)
    last_joined_at = models.DateTimeField(auto_now=True)
    join_count = models.PositiveSmallIntegerField(default=1)

    class Meta:
        unique_together = ['live_class', 'user']
