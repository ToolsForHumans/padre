from datetime import datetime
from datetime import timedelta

import pytz
from testtools import TestCase

from padre import date_utils as du


class DateUtilsTest(TestCase):
    ZERO_TIME = datetime.fromtimestamp(0, pytz.utc)

    def test_parsing_expected(self):
        dates = [
            # (Date str, user_tz)
            # These dates tz should match specified, and when not: 'US/Arizona'
            ('2018-07-20 17:00', None),
            ('2018-07-20 17:00', 'US/Arizona'),
            ('2018-07-20 17:00:00', 'MST'),
            ('2018-07-20T17:00', None),
            ('2018-07-20T17:00', 'US/Arizona'),
            ('2018-07-20T17:00:00', 'EST'),
            # None of the following should ever consider user_tz
            ('2018-07-20 17:00:00-08:00', None),
            ('2018-07-20 17:00:00-07:00', 'America/Phoenix'),
            ('2018-07-20T17:00:00-08:00', None),
            ('2018-07-20T17:00:00-07:00', 'America/Phoenix'),
            # Other variants
            # Shorter versions of times
            ('2018-07-20 17:00', 'MST'),  # missing seconds
            ('2018-07-20T17:00', None),  # missing seconds with T

            ('2018-07-20T17:00', 'US/Arizona'),  # missing seconds
            ('2018-07-20 17:00-08:00', None),  # missing seconds
            ('2018-07-20 17-04:00', 'America/Phoenix'),  # missing hour/minutes
            ('2018-07-20 17', 'EST'),  # missing hour/minutes
        ]
        dw = du.DateWrangler(default_tz='US/Arizona')
        for date_str, user_tz in dates:
            self.assertEqual(
                dw.parse(date_str, tz=user_tz),
                dw.parse_iso8601(date_str, tz=user_tz))

    def test_when(self):
        self.assertEqual(du.format_when(self.ZERO_TIME), 'evening')
        dt_morning = self.ZERO_TIME + timedelta(hours=8)
        self.assertEqual(du.format_when(dt_morning), 'morning')
        dt_afternoon = self.ZERO_TIME + timedelta(hours=12)
        self.assertEqual(du.format_when(dt_afternoon), 'afternoon')
