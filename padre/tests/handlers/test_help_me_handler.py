import requests_mock
from testtools import TestCase

from padre import channel as c
from padre import handler
from padre.handlers import help_me
from padre.tests import common


class HelpMeHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = common.make_bot()

        m = common.make_message(text="help me", to_me=True)
        self.assertTrue(help_me.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="help anyone", to_me=True)
        self.assertEqual(
            help_me.Handler.handles(m, c.TARGETED, bot.config), None)

    def test_help_me_call(self):
        bot = common.make_bot()

        m = common.make_message(text="consult me",
                                to_me=True, user_id="me")

        with requests_mock.mock() as req_m:
            req_m.get(help_me.Handler.buzz_url, text="you have been helped")
            h = help_me.Handler(bot, m)
            h.run(handler.HandlerMatch())

        m.reply_text.assert_called_once()
