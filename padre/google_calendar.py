import logging

from padre import utils

from dateutil import parser
from google.oauth2 import service_account
from googleapiclient import discovery
import munch
import pytz
import six

LOG = logging.getLogger(__name__)


def _from_date(dt):
    date_time = parser.parse(dt['date_time'])
    time_zone = dt.get('time_zone')
    if time_zone:
        return date_time.astimezone(pytz.timezone(time_zone))
    else:
        return date_time


def _to_date(dt):
    return {
        'dateTime': dt.isoformat(),
    }


def _munchify_and_clean(item):
    tmp_item = munch.Munch()
    for k, v in six.iteritems(item):
        k = utils.camel_to_underscore(k)
        if isinstance(v, dict):
            v = _munchify_and_clean(v)
        tmp_item[k] = v
    return tmp_item


def _consume_list(list_api, kwargs, execute_kwargs, item_key='items'):
    items = []
    result = list_api(**kwargs).execute(**execute_kwargs)
    while result:
        tmp_items = result.get(item_key, [])
        items.extend(tmp_items)
        next_token = result.get('nextPageToken')
        if not tmp_items or not next_token:
            break
        else:
            tmp_kwargs = kwargs.copy()
            tmp_kwargs['pageToken'] = next_token
            if 'nextSyncToken' in result:
                tmp_kwargs['syncToken'] = result['nextSyncToken']
            result = list_api(**tmp_kwargs).execute(**execute_kwargs)
    return items


class Calendar(object):
    """Helper class for interacting with google calendar apis.

    TODO: add timeout support.

    See: https://developers.google.com/calendar/
    """
    DEFAULT_CALENDAR_ID = 'primary'

    def __init__(self, config, auto_setup=False):
        self.default_calendar_id = config.get('default_calendar_id',
                                              self.DEFAULT_CALENDAR_ID)
        self.credentials = (service_account.Credentials.
                            from_service_account_info(config))
        self._service = None
        if auto_setup:
            self.setup()

    def setup(self):
        """Setups up the underlying service object."""
        self._service = discovery.build('calendar', 'v3',
                                        credentials=self.credentials)

    @staticmethod
    def _clean_event(event):
        event = _munchify_and_clean(event)
        for k in ('start', 'end'):
            event[k] = _from_date(event[k])
        for k in ('created', 'updated'):
            event[k] = parser.parse(event[k])
        return event

    def create_event(self, start, end, description=None, summary=None,
                     location=None, status='confirmed',
                     visibility='default', calendar_id=None,
                     num_retries=0):
        """Creates an event on some calendar."""
        if not calendar_id:
            calendar_id = self.default_calendar_id
        events_api = self._service.events()
        body = {
            'start': _to_date(start),
            'end': _to_date(end),
        }
        if description:
            body['description'] = description
        if summary:
            body['summary'] = summary
        if location:
            body['location'] = location
        if status:
            body['status'] = status
        if visibility:
            body['visibility'] = visibility
        event = events_api.insert(calendarId=calendar_id,
                                  body=body).execute(num_retries=num_retries)
        return self._clean_event(event)

    def list_calendars(self, max_results_per_page=10, num_retries=0):
        """List accessible calendars."""
        list_api = self._service.calendarList()
        calendars = _consume_list(
            list_api.list,
            {
                'maxResults': max_results_per_page,
            },
            {
                'num_retries': num_retries,
            })
        return [_munchify_and_clean(c) for c in calendars]

    def list_events(self, start_date, end_date=None, calendar_id=None,
                    max_results_per_page=10, num_retries=0):
        """List calendar events (starting at given datetime)."""
        if not calendar_id:
            calendar_id = self.default_calendar_id
        event_api = self._service.events()
        event_params = {
            'calendarId': calendar_id,
            'timeMin': start_date.isoformat(),
            'maxResults': max_results_per_page,
            'singleEvents': True,
            'orderBy': 'startTime',
        }
        if end_date is not None:
            event_params['timeMax'] = end_date.isoformat()
        events = _consume_list(
            event_api.list,
            event_params,
            {
                'num_retries': num_retries,
            })
        return [self._clean_event(event) for event in events]
