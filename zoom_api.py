from zoom import secrets

from authlib.jose import jwt
from datetime import datetime
import time
import requests
import json
from sortedcontainers import SortedList
import xmltodict

API_BASE = 'https://api.zoom.us/v2'
MAX_PAGE_SIZE = 300

class Error(Exception):
    def __init__(self, code, data):
        self.code = code
        self.data = data

def load_json(text):
    try:
        return json.loads(text)
    except:
        pass

    try:
        return xmltodict.parse(text)
    except:
        pass

    return {'text': text}

# Generate a JWT token valid for the next `duration` seconds
def gen_token(duration=30):

    now = time.time()
    then = now + duration

    header = {'typ': 'JWT', 'alg': 'HS256'}
    payload = {'aud': None, 'iss': secrets.JWT_API_KEY, 'iat': str(round(now)), 'exp': str(round(then))}

    return jwt.encode(header, payload, secrets.JWT_SECRET)

# Perform a Zoom API request
# Returns the response as a JSON object
def zoom_request(token, path, params={}, method='GET'):
    headers = {'Authorization': 'Bearer %s' % token.decode('utf-8')}

    if method == 'GET':
        rep = requests.get('%s/%s' % (API_BASE, path), headers=headers, params=params)

    if method == 'POST':
        headers['Content-Type'] = 'application/json'
        rep = requests.post('%s/%s' % (API_BASE, path), headers=headers, data=json.dumps(params))

    if method == 'PATCH':
        headers['Content-Type'] = 'application/json'
        rep = requests.patch('%s/%s' % (API_BASE, path), headers=headers, data=json.dumps(params))

    if 200 <= rep.status_code < 300:
        return load_json(rep.text), rep.status_code

    raise Error(rep.status_code, load_json(rep.text))

# List upcoming meetings
def list_meetings(token, user='me', typ='upcoming'):
    data, code = zoom_request(token, 'users/%s/meetings' % user, params={'type': typ})
    data['meetings'].sort(key=lambda m: m['start_time'])
    return data['meetings'], code

# Get details about a specific meeting
# Includes start URL but not registrants
def get_meeting(token, meeting_id):
    return zoom_request(token, 'meetings/%d' % meeting_id)

# Updates a meeting
def update_meeting(token, meeting_id, updates):
    return zoom_request(token, 'meetings/%d' % meeting_id, params=updates, method='PATCH')

# Creates a new meeting
# Returns meeting ID
def create_meeting(token, meeting, user='me'):
    return zoom_request(token, 'users/%s/meetings' % user, params=meeting, method='POST')

# Get registrants for a specific meeting
# Returns name, email, location (if given) and answers to the questions (if any)
# Sorts by last name
#
# TODO: support recurring meetings by passing the occurence_id param
def get_registrants(token, meeting_id):
    data, code = zoom_request(token, 'meetings/%d/registrants' % meeting_id, params={'page_size': MAX_PAGE_SIZE})

    # Sometimes people put their full name in the "First name" box, so r['last_name'] might not exist.
    # For a best-effort (but by no means foolproof) sort by last name, we join whatever was entered in
    # the first and last name boxes, then take the final space-delimited word as the last name.
    # Similar data cleaning is performed on the location fields.

    def combine(row, *fields):
        return filter(lambda x: x, map(lambda f: row.get(f, None), fields))

    regs = list(
            map(lambda r: {
                    'name': ' '.join(combine(r, 'first_name', 'last_name')),
                    'email': r['email'].lower(),
                    'location': ', '.join(combine(r, 'city', 'state', 'country')) or 'Unknown',
                    'answers': r['custom_questions'],
                },
                data['registrants']))
    regs.sort(key=lambda r: r['name'].split(' ')[-1].lower())

    return regs, code

# Get list of people who actually attended a specific meeting (must be in the past)
#
# Returns names, emails, and total minutes in the meeting
#
# NB: for a recurring meeting you must pass its UUID insetad of ID, or you'll always get the most recent occurrence
def get_participants(token, meeting_id):
    # Totals the duration of a set of time intervals,
    # but without double-counting overlaps.
    #
    # Ported from the following Haskell (thanks, Antal):
    # unionSorted :: Ord a => [(a,a)] -> [(a,a)]
    # unionSorted [] = []
    # unionSorted [interval] = [interval]
    # unionSorted ((start1,end1):(start2,end2):intervals)
    #   | start2 <= end1 = unionSorted $ ((start1, end1 `max` end2) : intervals)
    #   | otherwise      = (start1,end1) : unionSorted ((start2,end2) : intervals)
    def union_sorted(intervals):
        if len(intervals) <= 1:
            return intervals

        a = intervals[0]
        b = intervals[1]

        if b[0] <= a[1]:
            return union_sorted([(a[0], max(a[1], b[1]))] + intervals[2:])

        return [a] + union_sorted(intervals[1:])

    data, code = zoom_request(token, 'report/meetings/%d/participants' % meeting_id, params={'page_size': MAX_PAGE_SIZE})

    # merge records using email as primary key
    people = {}
    for record in data['participants']:
        email = record['user_email'].lower()
        if email == '':
            # not sure why this happens...
            continue

        if email not in people:
            people[email] = {'name': record['name'], 'intervals': SortedList()}

        # first pass: collect intervals in sorted order
        people[email]['intervals'].add(tuple(map(lambda s: datetime.strptime(record[s + '_time'], '%Y-%m-%dT%H:%M:%SZ'), ('join', 'leave'))))

    # second pass: combine intervals to avoid double-counting
    for email in people.keys():
        intervals = list(people[email]['intervals']) # extract list from SortedList
        del people[email]['intervals']
        people[email]['duration'] = sum(map(lambda iv: (iv[1] - iv[0]).total_seconds() / 60, union_sorted(intervals)))

    return people, code

