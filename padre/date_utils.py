import datetime

from dateutil import parser as dateutil_parser
import iso8601
import pytz
import six

DEFAULT_TZ = 'US/Arizona'
MORNING_HOURS = tuple(range(5, 12))
AFTER_NOON_HOURS = tuple(range(12, 18))
FIVE_MINUTES = datetime.timedelta(minutes=5)


def get_now(tz=None, default_tz=DEFAULT_TZ):
    if not tz:
        tz = default_tz
    if isinstance(tz, six.string_types):
        tz = pytz.timezone(tz)
    return datetime.datetime.now(tz=tz)


def format_when(dt):
    if dt.hour in MORNING_HOURS:
        when = 'morning'
    elif dt.hour in AFTER_NOON_HOURS:
        when = 'afternoon'
    else:
        when = 'evening'
    return when


def get_when(tz=None, default_tz=DEFAULT_TZ):
    now = get_now(tz=tz, default_tz=default_tz)
    return format_when(now)


class DateWrangler(object):
    """Wrangles some dates or datetime like things."""

    def __init__(self, default_tz=None):
        if not default_tz:
            default_tz = DEFAULT_TZ
        self._default_tz = default_tz

    @property
    def default_tz(self):
        return self._default_tz

    def parse(self, date_str, tz=None):
        """Date decoder via dateutil (and its various accepted formats)."""
        date = dateutil_parser.parse(date_str)
        if date.tzinfo:
            return date
        else:
            local_tz = pytz.timezone(tz) if tz else pytz.timezone(
                self.default_tz)
            return local_tz.localize(date)

    def parse_iso8601(self, date_str, tz=None):
        """Date decoder via iso8601 (and its various accepted formats)."""
        date = iso8601.parse_date(date_str, default_timezone=None)
        if date.tzinfo:
            return date
        else:
            local_tz = pytz.timezone(tz) if tz else pytz.timezone(
                self.default_tz)
            return local_tz.localize(date)

    def get_now(self, tz=None):
        """Gets current time (in some tz)."""
        return get_now(tz=tz, default_tz=self.default_tz)

    def get_when(self, tz=None):
        """One of [morning, afternoon, evening] according to current time."""
        return get_when(tz=tz, default_tz=self.default_tz)
