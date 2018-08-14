from testtools import TestCase

import requests_mock

from padre import channel as c
from padre import handler
from padre.handlers import tell_joke
from padre.tests import common


class TellJokeHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = common.make_bot()

        m = common.make_message(text="tell me a joke", to_me=True)
        self.assertTrue(tell_joke.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="please, don't tell me anything",
                                to_me=True)
        self.assertEqual(
            tell_joke.Handler.handles(m, c.TARGETED, bot.config), None)

    def test_tell_joke(self):
        bot = common.make_bot()

        m = common.make_message(text="tell me a joke",
                                to_me=True, user_id="me")

        h = tell_joke.Handler(bot, m)

        with requests_mock.mock() as req_m:
            req_m.get(h.joke_url, json={"joke": 'an amazing joke'})
            h.run(handler.HandlerMatch())

        m.reply_text.assert_called_once_with('an amazing joke',
                                             prefixed=False, threaded=True)

    def test_joke_is_unavailable(self):
        bot = common.make_bot()

        m = common.make_message(text="tell me a joke",
                                to_me=True, user_id="me")

        h = tell_joke.Handler(bot, m)

        with requests_mock.mock() as req_m:
            req_m.get(h.joke_url, json={})
            h.run(handler.HandlerMatch())

        m.reply_text.assert_called_once_with(
            'No joke found when calling `%s`.' % h.joke_url,
            prefixed=False, threaded=True)
