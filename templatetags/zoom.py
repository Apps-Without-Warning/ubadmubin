import datetime

from django import template
register = template.Library()

# Parse a date from Zoom's idiosyncratic format into a datetime
@register.filter
def zoom_date(dt_str):
    assert dt_str[-1] == 'Z'
    dt = datetime.datetime.strptime(dt_str, '%Y-%m-%dT%H:%M:%SZ')
    return dt.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=0)))

# Split a string on a delimiter
@register.filter
def split(string, delimiter):
    return string.split(delimiter)

# Add a number of minutes to a datetime
@register.filter
def add_minutes(dt, minutes):
    return dt + datetime.timedelta(minutes=minutes)

@register.filter
def lookup(d, k):
    '''Returns the given key from a dictionary.'''
    return d[k]

