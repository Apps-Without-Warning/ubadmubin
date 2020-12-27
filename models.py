from datetime import datetime, timedelta
import pytz
import json

from django.db import models
from django.contrib.auth import models as auth_models
from django.db.models.signals import post_save
from django.dispatch import receiver

from zoom import zoom_api as zoom

class Event(models.Model):
    EVENT_TYPES = [
            ('ST', 'Start Meeting'),
            ('UP', 'Edit Meeting'),
            ('CR', 'Create Meeting'),
        ]

    timestamp = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(auth_models.User, on_delete=models.CASCADE)
    event = models.CharField(max_length=2, choices=EVENT_TYPES)
    meeting_id = models.BigIntegerField()
    data = models.TextField(default='', blank=True)

    def __str__(self):
        verbs = {'ST': 'started', 'UP': 'edited', 'CR': 'created'}
        return '[%s] %s (%s) %s %s' % (self.timestamp.astimezone().strftime('%c %Z'), self.user, ' '.join([self.user.first_name, self.user.last_name]), verbs[self.event], self.meeting_id)

class Webhook(models.Model):
    EVENT_TYPES = [
            ('MS', 'Meeting Started'),
            ('ME', 'Meeting Ended'),
            ('JWR', 'Joined Waiting Room'),
            ('MRC', 'Registration Created'),
        ]

    timestamp = models.DateTimeField(auto_now_add=True)
    event = models.CharField(max_length=3, choices=EVENT_TYPES)
    meeting_id = models.BigIntegerField()
    data = models.TextField(default='', blank=True)

    def __str__(self):
        return '[%s] %s(%s): %s' % (self.timestamp.astimezone().strftime('%c %Z'), self.event, self.meeting_id, self.data)

class Meeting(models.Model):
    meeting_id = models.BigIntegerField()
    title = models.TextField()
    description = models.TextField()
    time = models.DateTimeField()
    duration = models.DurationField()
    registrants = models.IntegerField()
    participants = models.IntegerField()

    def __str__(self):
        return '[%s] %s (%s|%s)' % (self.time.astimezone().strftime('%c %Z'), self.title, self.registrants, self.participants)

def archive_meeting(meeting_id):
    token = zoom.gen_token()
    try:
        meeting, _ = zoom.get_meeting(token, meeting_id)
        if meeting['type'] == 2: # non-recurrint meeting
           if  meeting['settings']['approval_type'] == 0: # registration required and auto-approved
                registrants, _ = zoom.get_registrants(token, meeting_id)
                participants, _ = zoom.get_participants(token, meeting_id)

                meeting_obj = Meeting.objects.create(meeting_id=meeting_id, title=meeting['topic'], description=meeting['agenda'], time=pytz.utc.localize(datetime.strptime(meeting['start_time'], '%Y-%m-%dT%H:%M:%SZ')), duration=timedelta(minutes=meeting['duration']), registrants=len(registrants), participants=len(participants))
                meeting_obj.save()
    except:
        pass

@receiver(post_save, sender=Webhook)
def on_webhook(sender, instance, created, **kwargs):
    if created:
        if instance.event == 'ME':
            archive_meeting(instance.meeting_id)

