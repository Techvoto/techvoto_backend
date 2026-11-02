from django.contrib import admin

from .models import Attendance, LiveClass

admin.site.register([LiveClass, Attendance])
