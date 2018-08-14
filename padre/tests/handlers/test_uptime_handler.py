import mock
import pytz

from datetime import datetime
from testtools import TestCase

from padre import channel as c
from padre import handler
from padre.handlers import uptime
from padre.tests import common


class UptimeHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = common.make_bot()

        m = common.make_message(text="uptime", to_me=True)
        self.assertTrue(uptime.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="non-uptime", to_me=True)
        self.assertEqual(
            uptime.Handler.handles(m, c.TARGETED, bot.config), None)

    def test_uptime_is_zero(self):
        bot = common.make_bot()
        bot.started_at = None

        m = common.make_message(text="uptime",
                                to_me=True, user_id="me")

        h = uptime.Handler(bot, m)
        h.run(handler.HandlerMatch())

        m.reply_text.assert_called_once_with(
            "I am not alive, how are you sending this?",
            threaded=True, prefixed=False)

    @mock.patch("padre.date_utils.get_now")
    def test_uptime_is_not_zero(self, mock_now):
        bot = common.make_bot()
        bot.started_at = datetime.now(tz=pytz.timezone('UTC'))
        bot.config.tz = 'UTC'
        mock_now.return_value = bot.started_at

        m = common.make_message(text="uptime",
                                to_me=True, user_id="me")

        h = uptime.Handler(bot, m)
        h.run(handler.HandlerMatch())

        m.reply_text.assert_called_once_with(
            'I have been alive for 0 seconds.',
            prefixed=False, threaded=True)
