from django.db import models
from django.contrib.auth import models as auth_models

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
        return '%s (%s) %s %s at %s' % (self.user, ' '.join([self.user.first_name, self.user.last_name]), verbs[self.event], self.meeting_id, self.timestamp.astimezone().strftime('%c %Z'))

