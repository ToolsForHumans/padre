from __future__ import unicode_literals

from datetime import datetime
import json
import mock
from testtools import TestCase, ExpectedException  # noqa

from padre import channel as c
from padre.tests import common
from padre.wsgi_servers import status


def _mock_best_match(items):
    if not items:
        return None
    return items[0]


class StatusWatcherTest(TestCase):
    t0 = datetime.fromtimestamp(0)
    t0_iso = t0.isoformat()

    def setUp(self):
        super(StatusWatcherTest, self).setUp()
        self.bot = common.make_bot()
        self.bot.started_at = datetime.now()
        self.hook = status.StatusApplication(self.bot)
        self.slack_client = mock.MagicMock()
        self.maxDiff = None

    @mock.patch("padre.date_utils.get_now")
    def test_reply_successful(self, mock_now):
        mock_now.return_value = self.bot.started_at
        req = mock.MagicMock()
        req.accept.best_match.side_effect = _mock_best_match
        req.headers.get.return_value = None
        self.hook.bot.message_stats = dict()
        resp = {
            'uptime': {
                'days': 0,
                'seconds': 0,
                'hours': 0,
                'minutes': 0,
                'weeks': 0,
                'years': 0,
            },
            'clients': [],
            'watchers': [],
            'wsgi_servers': [],
            'channel_stats': {},
            'handlers': {
                'active': [],
                'prior': {},
                'stats': {},
            },
        }
        self.assertDictEqual(
            resp,
            json.loads(self.hook.reply_status(req, None).body))

    def test_reply_successful_without_started_time(self):
        req = mock.MagicMock()
        req.accept.best_match.side_effect = _mock_best_match
        req.headers.get.return_value = None
        self.hook.bot.message_stats = dict()
        self.hook.bot.started_at = None
        resp = {
            'uptime': {},
            'clients': [],
            'watchers': [],
            'wsgi_servers': [],
            'channel_stats': {},
            'handlers': {
                'active': [],
                'prior': {},
                'stats': {},
            },
        }
        self.assertDictEqual(
            resp,
            json.loads(self.hook.reply_status(req, None).body))

    def test_reply_successful_with_active_handlers(self):
        req = mock.MagicMock()
        req.accept.best_match.side_effect = _mock_best_match
        req.headers.get.return_value = None
        handler = mock.MagicMock()
        handler.state = 'active'
        handler.watch.elapsed.return_value = 0
        handler.created_on = self.t0
        handler.message = mock.MagicMock()
        handler.message.to_dict.return_value = {}
        self.hook.bot.prior_handlers = {}
        self.hook.bot.active_handlers = [handler]
        self.hook.bot.message_stats = dict()
        self.hook.bot.started_at = None
        resp_active = [{
            'class': mock.ANY,
            'elapsed': 0,
            'state': 'active',
            'state_history': [],
            'created_on': self.t0_iso,
            'message': {},
        }]
        resp = {
            'uptime': {},
            'clients': [],
            'watchers': [],
            'wsgi_servers': [],
            'channel_stats': {},
            'handlers': {
                'active': resp_active,
                'prior': {},
                'stats': {},
            },
        }
        self.assertDictEqual(
            resp,
            json.loads(self.hook.reply_status(req, None).body))

    def test_reply_successful_without_elapsed_time(self):
        req = mock.MagicMock()
        req.accept.best_match.side_effect = _mock_best_match
        req.headers.get.return_value = None
        handler = mock.MagicMock()
        handler.state = 'active'
        handler.watch.elapsed.side_effect = RuntimeError('Error')
        handler.created_on = self.t0
        handler.message = mock.MagicMock()
        handler.message.to_dict.return_value = {}
        self.hook.bot.active_handlers = [handler]
        self.hook.bot.message_stats = dict()
        self.hook.bot.started_at = None
        resp_active = [{
            'class': mock.ANY,
            'elapsed': None,
            'state': 'active',
            'state_history': [],
            'created_on': self.t0_iso,
            'message': {},
        }]
        resp = {
            'uptime': {},
            'clients': [],
            'watchers': [],
            'wsgi_servers': [],
            'channel_stats': {},
            'handlers': {
                'active': resp_active,
                'prior': {},
                'stats': {},
            },
        }
        self.assertDictEqual(
            resp,
            json.loads(self.hook.reply_status(req, None).body))

    def test_reply_successful_with_prior_handlers(self):
        req = mock.MagicMock()
        req.accept.best_match.side_effect = _mock_best_match
        req.headers.get.return_value = None
        handler = mock.MagicMock()
        handler.state = 'active'
        handler.watch.elapsed.side_effect = RuntimeError('Error')
        handler.created_on = self.t0
        handler.message = mock.MagicMock()
        handler.message.to_dict.return_value = {}
        self.hook.bot.prior_handlers = {
            c.TARGETED: {
                'slack': [handler],
            },
        }
        self.hook.bot.message_stats = dict()
        self.hook.bot.started_at = None
        resp = {
            'uptime': {},
            'channel_stats': {},
            'clients': [],
            'watchers': [],
            'wsgi_servers': [],
            'handlers': {
                'active': [],
                'prior': {
                    'targeted': {
                        'slack': [
                            {
                                'class': mock.ANY,
                                'elapsed': None,
                                'state': 'active',
                                'state_history': [],
                                'created_on': self.t0_iso,
                                'message': {},
                            }
                        ],
                    }
                },
                'stats': {},
            },
        }
        self.assertDictEqual(
            resp,
            json.loads(self.hook.reply_status(req, None).body))

    def test_reply_successful_without_tz_set(self):
        req = mock.MagicMock()
        req.accept.best_match.side_effect = _mock_best_match
        req.headers.get.return_value = None
        handler = mock.MagicMock()
        handler.state = 'active'
        handler.watch.elapsed.side_effect = RuntimeError('Error')
        handler.created_on = self.t0
        handler.message = mock.MagicMock()
        handler.message.to_dict.return_value = {}
        self.hook.bot.prior_handlers = {
            c.TARGETED: {
                'slack': [handler],
            },
        }
        self.hook.bot.message_stats = dict()
        delattr(self.hook.bot.config, 'tz')
        self.hook.bot.started_at = None
        resp = {
            'uptime': {},
            'clients': [],
            'watchers': [],
            'wsgi_servers': [],
            'channel_stats': {},
            'handlers': {
                'active': [],
                'prior': {
                    'targeted': {
                        'slack': [
                            {
                                'class': mock.ANY,
                                'elapsed': None,
                                'state': 'active',
                                'state_history': [],
                                'created_on': self.t0_iso,
                                'message': {},
                            }
                        ],
                    },
                },
                'stats': {},
            },
        }
        self.assertDictEqual(
            resp,
            json.loads(self.hook.reply_status(req, None).body))
