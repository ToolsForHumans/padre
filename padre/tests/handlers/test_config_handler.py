import mock
import munch
from testtools import TestCase

from padre import channel as c
from padre import handler
from padre.handlers import config
from padre.tests import common


class ConfigHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = mock.MagicMock()
        bot.config = munch.Munch()

        m = common.make_message(text="show config", to_me=True)
        self.assertTrue(config.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="config show", to_me=True)
        self.assertTrue(config.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="show configuration", to_me=True)
        self.assertEqual(config.Handler.handles(m, c.TARGETED,
                                                bot.config), None)

    def test_show_config(self):
        bot = common.make_bot(simple_config=True)
        m = common.make_message(text="show config", to_me=True, user_id="me")
        h = config.Handler(bot, m)
        h.run(handler.HandlerMatch())

        m.reply_text.assert_called_once_with(
            "I am running with configuration:\n```\npassword: '***'\nuser:"
            " AwesomeUser\n\n```",
            prefixed=True,
            threaded=True)
