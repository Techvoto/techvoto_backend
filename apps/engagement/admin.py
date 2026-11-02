from django.contrib import admin

from .models import Announcement, Notification, Reply, Thread

admin.site.register([Notification, Announcement, Thread, Reply])
