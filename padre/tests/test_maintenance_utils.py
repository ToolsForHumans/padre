import datetime as dt
import pytz

import requests_mock
from testtools import TestCase

from padre import maintenance_utils as mu


class ServiceNowTest(TestCase):
    def _gen_test_date(self, minutes_offset=30):
        return dt.datetime.now(tz=pytz.timezone('UTC')) \
            + dt.timedelta(minutes=minutes_offset)

    def test_create_change(self):
        snow = mu.ServiceNow("test", "user", "secrete")
        with requests_mock.mock() as req_m:
            req_m.post(requests_mock.ANY, json={'result': {'sys_id': '3'}})
            chg = snow.create_change("test_sd", "test_desc", "test_plan",
                                     "test_group", self._gen_test_date(0),
                                     self._gen_test_date(60))
            self.assertEqual(
                chg, {'sys_id': '3',
                      'link': '%s/3' % snow.table_endpoints['change_request']})

    def test_find_ci(self):
        snow = mu.ServiceNow("test", "user", "secrete")
        with requests_mock.mock() as req_m:
            req_m.get(requests_mock.ANY, json={'result': [{}]})
            chg = snow.find_ci(name="test")
            self.assertEqual(chg, {})
