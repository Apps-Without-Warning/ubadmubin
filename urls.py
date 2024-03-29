from django.urls import path

from . import views

urlpatterns = [
    # list of meetings
    path('meetings', views.meetings, name='meetings'),

    # meeting details (non-recurring)
    path('meeting/<int:meeting_id>', views.meeting, name='meeting'),

    # meeting details (recurring)
    path('meeting/<int:meeting_id>/<int:occurrence_id>', views.meeting, name='meeting'),

    # attendance records
    path('attendance', views.attendance, name='attendance'),

    # start meeting redirect
    path('start/<int:meeting_id>/<str:encoded_url>', views.start, name='start'),

    # webhook event notification
    path('webhook', views.webhook, name='webhook'),
]


