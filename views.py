from datetime import datetime, timedelta
import pytz
import json
import urllib

from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from zoom import zoom_api as zoom
from zoom import secrets
from zoom.models import Event, Webhook

# Helper class for a view to return a template to be rendered, along with the data
class TemplateInvocation(object):
    def __init__(self, filename, data):
        self.filename = filename
        self.data = data

# View decorator that calculates processing time and adds it to the template data, if applicable
# The wrapped view should return a TemplateInvocation, or some other response that will be passed through
def processing_time(view):
    def timed_view(request, *args, **kwargs):
        start = datetime.now()

        result = view(request, *args, **kwargs)

        if isinstance(result, TemplateInvocation):
            result.data['processing_time'] = (datetime.now() - start)

            return render(request, result.filename, result.data)
        else:
            return result

    return timed_view

# Receive a web hook event notification from Zoom
@csrf_exempt
@require_POST
def webhook(request):
    events = {
            'meeting.participant_joined_waiting_room': ('JWR', 'participant'),
            'meeting.registration_created': ('MRC', 'registrant'),
        }

    if request.headers.get('authorization', '') != secrets.WEBHOOK_VERIFICATION_TOKEN:
        return HttpResponse('Bad authorization', status=403)
    else:
        data = json.loads(request.body)
        hook = Webhook.objects.create(event=events[data['event']][0], meeting_id=data['payload']['object']['id'], data=data['payload']['object'][events[data['event']][1]])
        hook.save()
        return HttpResponse('Webhook received')

# Record a click on the Start Meeting button
@login_required
def start(request, meeting_id, encoded_url):
    event = Event.objects.create(user=request.user, event='ST', meeting_id=meeting_id)
    event.save()
    return HttpResponseRedirect(urllib.parse.unquote(encoded_url))

# Show a list of upcoming meetings
@login_required
@processing_time
def meetings(request):
    if 'crash' in request.GET:
        raise Exception('oh no')
    token = zoom.gen_token()
    if 'type' in request.GET:
        meetings, _ = zoom.list_meetings(token, typ=request.GET['type'])
    else:
        meetings, _ = zoom.list_meetings(token)
    return TemplateInvocation('zoom/meetings.html', {'meetings': meetings})

# Show details about a single meeting
# If method==POST, update meeting details first
@login_required
@processing_time
def meeting(request, meeting_id, occurrence_id=None):
    data = {}

    token = zoom.gen_token()

    editable_settings = [
        ('waiting_room', 'Use waiting room', 'boolean'),
        ('request_permission_to_unmute_participants', 'Request permission to unmute participants', 'boolean'),
    ]

    try:
        meeting, _ = zoom.get_meeting(token, meeting_id)
    except zoom.Error as e:
        data['response_code'] = e.code
    else:
        if request.method == 'POST':
            post = {k: urllib.parse.unquote(v) for k, v in request.POST.items()}
            if post['action'] == 'settings':
                updates = {'settings': {}}

                for setting in editable_settings:
                    if setting[2] == 'boolean':
                        updates['settings'][setting[0]] = setting[0] in post

                event = Event.objects.create(user=request.user, event='UP', meeting_id=meeting_id, data=json.dumps(updates))
                event.save()

                try:
                    _, code = zoom.update_meeting(token, meeting_id, updates)
                    error = ''
                except zoom.Error as e:
                    code = e.code
                    error = urllib.request.quote(json.dumps(e.data))

                return HttpResponseRedirect('?response_code=%d&error=%s' % (code, error)) # redirect so that refreshing doesn't POST again
            else:
                assert 'ocurrences' not in meeting, 'Editing recurring meetings is not supported'

                updates = {}

                # use a whitelist of properties that can be set
                for prop in ('topic', 'password', 'agenda'):
                    updates[prop] = post[prop]

                # start_time is split into three properties
                updates['start_time'] = '%(start_time-date)sT%(start_time-time)s:00' % post
                updates['timezone'] = post['timezone']

                # duration is passed as end_time
                fmt = '%Y-%m-%dT%H:%M:%S'
                start = datetime.strptime(updates['start_time'], fmt)
                end = datetime.strptime('%(start_time-date)sT%(end_time)s:00' % post, fmt)
                updates['duration'] = round((end - start).seconds / 60)

                if post['action'] == 'update':
                    # edit the current meeting, then show it again

                    event = Event.objects.create(user=request.user, event='UP', meeting_id=meeting_id, data=json.dumps(updates))
                    event.save()

                    try:
                        _, code = zoom.update_meeting(token, meeting_id, updates)
                        error = ''
                    except zoom.Error as e:
                        code = e.code
                        error = urllib.request.quote(json.dumps(e.data))

                    return HttpResponseRedirect('?response_code=%d&error=%s' % (code, error)) # redirect so that refreshing doesn't POST again

                elif post['action'] == 'create':
                    # create a new meeting, then show that one

                    for k, v in updates.items():
                        meeting[k] = v

                    event = Event.objects.create(user=request.user, event='CR', meeting_id=meeting_id, data=json.dumps(meeting))
                    event.save()

                    try:
                        meeting, code = zoom.create_meeting(token, meeting)
                    except zoom.Error as e:
                        code = e.code
                        error = urllib.request.quote(json.dumps(e.data))
                        return HttpResponseRedirect('?response_code=%d&error=%s' % (code, error)) # redirect so that refreshing doesn't POST again

                    return redirect('meeting', meeting_id=meeting['id'])

        # this is now a GET request, show the meeting info

        if meeting['settings']['approval_type'] == 2: # registration not required
            registrants = None
        else:
            registrants, _ = zoom.get_registrants(token, meeting_id)

        # for a recurring meeting, search for a occurrence we want
        if 'occurrences' in meeting:
            for occurrence in meeting['occurrences']:
                if int(occurrence['occurrence_id']) == occurrence_id:
                    meeting['start_time'] = occurrence['start_time']
                    meeting['duration'] = occurrence['duration']
                    break

        data['meeting'] = meeting
        data['registrants'] = registrants
        data['editable_settings'] = editable_settings

        try:
            # if it's a past meeting, get attendees (FIXME won't work for recurring meetings)
            if pytz.utc.localize(datetime.strptime(meeting['start_time'], '%Y-%m-%dT%H:%M:%SZ')) + timedelta(minutes=int(meeting['duration'])) < datetime.now(pytz.utc):
                data['participants'], _ = zoom.get_participants(token, meeting_id)

                # also get users who started this meeting
                data['starters'] = User.objects.filter(event__meeting_id=meeting_id, event__event='ST')
        except Exception as e:
            data['error_message'] = 'Couldn\'t fetch attendee data: %s' % e

    if 'response_code' in request.GET:
        data['response_code'] = int(request.GET['response_code'])
    if 'error' in request.GET:
        data['error'] = zoom.load_json(request.GET['error'])
    return TemplateInvocation('zoom/meeting.html', data)

