import ast
from datetime import datetime, timedelta
import pytz
import json
import traceback

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
    raw = models.TextField(default='', blank=True)

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

    class Meta:
        ordering = ['-time']

    def __str__(self):
        return '%s [%s] %s (%s|%s)' % (self.meeting_id, self.time.astimezone().strftime('%c %Z'), self.title, self.registrants, self.participants)

def archive_meeting(event, keep_data=False):
    token = zoom.gen_token()
    meeting_id = int(event.meeting_id)
    raw = json.loads(event.raw)
    try:
        meeting, _ = zoom.get_meeting(token, meeting_id)
        if meeting['settings']['approval_type'] == 0: # registration required and auto-approved
            # Save a record of the attendance numbers based on what the Zoom API says
            try:
                registrants, _ = zoom.get_registrants(token, meeting_id)
                participants, _ = zoom.get_participants(token, meeting_id)
            except:
                # Sometimes these API calls for attendance fail with a "no such meeting" error
                # despite the fact that get_meeting just succeeded for the same meeting ID. No
                # idea why that happens, but there's not much we can do about it, so just silently
                # do nothing.
                pass
            else:
                meeting_obj = Meeting.objects.create(
                        meeting_id=meeting_id,
                        title=meeting['topic'],
                        description=meeting['agenda'],
                        time=pytz.utc.localize(datetime.strptime(meeting['start_time'], '%Y-%m-%dT%H:%M:%SZ')),
                        duration=timedelta(minutes=meeting['duration']),
                        registrants=len(registrants),
                        participants=len(participants))
                meeting_obj.save()

        # Save another record based on the number of webhook events received (this is always ~10% higher than the API numbers, no idea why)
        if meeting['type'] == 2: # non-recurring meeting
            hooks = Webhook.objects.filter(meeting_id=meeting_id)
        else:
            hooks = Webhook.objects.filter(meeting_id=meeting_id,
                    timestamp__gte=datetime.strftime(datetime.strptime(raw['payload']['object']['start_time'], '%Y-%m-%dT%H:%M:%SZ'), '%Y-%m-%d %H:%M:%S-00:00'),
                    timestamp__lte=datetime.strftime(datetime.strptime(raw['payload']['object']['end_time'], '%Y-%m-%dT%H:%M:%SZ'), '%Y-%m-%d %H:%M:%S-00:00'))
        reg_hooks = hooks.filter(meeting_id=meeting_id, event='MRC')
        part_hooks = hooks.filter(meeting_id=meeting_id, event='JWR')
        if len(part_hooks) > 0:
            meeting_obj = Meeting.objects.create(
                    meeting_id=meeting_id,
                    title=meeting['topic'] + ' (from events)',
                    description=meeting['agenda'],
                    time=pytz.utc.localize(datetime.strptime(raw['payload']['object']['start_time'], '%Y-%m-%dT%H:%M:%SZ')),
                    duration=datetime.strptime(raw['payload']['object']['end_time'], '%Y-%m-%dT%H:%M:%SZ') - datetime.strptime(raw['payload']['object']['start_time'], '%Y-%m-%dT%H:%M:%SZ'),
                    registrants=len(set(ast.literal_eval(h.data)['user_name'] for h in reg_hooks)),
                    participants=len(set(ast.literal_eval(h.data)['user_name'] for h in part_hooks)))
            meeting_obj.save()

        # purge collected data
        if not keep_data:
            hooks.delete()
            event.delete()
    except:
        print(traceback.format_exc())

        # create a "meeting" to record the error
        meeting_obj = Meeting.objects.create(
                meeting_id=meeting_id,
                title='Error cleaning up %s' % meeting_id,
                description=traceback.format_exc(),
                time=datetime.now(),
                duration=timedelta(0),
                registrants=0,
                participants=0)
        meeting_obj.save()

        # TODO email error report

@receiver(post_save, sender=Webhook)
def on_webhook(sender, instance, created, **kwargs):
    if created:
        if instance.event == 'ME':
            archive_meeting(instance)

