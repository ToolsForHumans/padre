from testtools import TestCase

import requests_mock

from padre import channel as c
from padre import handler
from padre.handlers import trump
from padre.tests import common


class TrumpHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = common.make_bot()

        m = common.make_message(text="what would trump say",
                                to_me=True)
        self.assertTrue(trump.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="what would trump say?",
                                to_me=True)
        self.assertTrue(trump.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="trump say something", to_me=True)
        self.assertTrue(trump.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="trump, it's enough", to_me=True)
        self.assertEqual(
            trump.Handler.handles(m, c.TARGETED, bot.config), None)

    def test_trump_says(self):
        bot = common.make_bot()

        m = common.make_message(text="trump say something",
                                to_me=True, user_id="me")

        h = trump.Handler(bot, m)

        with requests_mock.mock() as req_m:
            req_m.get(h.trump_url, json={
                'messages': {
                    'non_personalized': ["we're not in Kansas anymore"]
                }
            })
            h.run(handler.HandlerMatch())

        m.reply_text.assert_called_once_with("we're not in Kansas anymore",
                                             prefixed=False, threaded=True)
