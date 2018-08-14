from testtools import TestCase

from padre import channel as c
from padre import handler
from padre.handlers import help
from padre.tests import common


class HelpHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = common.make_bot()

        m = common.make_message(text="help", to_me=True)
        self.assertTrue(help.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="please, not help", to_me=True)
        self.assertEqual(help.Handler.handles(
            m, c.TARGETED, bot.config), None)

        m = common.make_message(text="help me", to_me=True)
        self.assertTrue(help.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="help anyone", to_me=True)
        self.assertTrue(help.Handler.handles(m, c.TARGETED, bot.config))

    def test_help_without_trigger(self):
        bot = common.make_bot()
        bot.handlers = [help.Handler]

        m = common.make_message(text="help", to_me=True, user_id="me")

        h = help.Handler(bot, m)
        h.run(handler.HandlerMatch())

        m.reply_attachments.assert_called()

    def test_help_without_trigger_with_given_slack_handlers(self):
        bot = common.make_bot()
        bot.handlers = [help.Handler]

        m = common.make_message(text="help",
                                to_me=True, user_id="me")

        h = help.Handler(bot, m)
        h.run(handler.HandlerMatch())

        m.reply_attachments.assert_called_once()

    def test_help_with_wrong_trigger(self):
        bot = common.make_bot()

        m = common.make_message(text="help",
                                to_me=True, user_id="me")

        h = help.Handler(bot, m)
        h.run(handler.HandlerMatch("deploy"))

        m.reply_text.assert_called_once_with(
            'Sorry I do not know of any trigger `deploy` (pick another?)',
            prefixed=False, threaded=True)

    def test_help_with_proper_trigger(self):
        bot = common.make_bot()
        bot.handlers = [help.Handler]

        m = common.make_message(
            text="help", to_me=True, user_id="me")

        h = help.Handler(bot, m)
        h.run(handler.HandlerMatch("help"))

        m.reply_attachments.assert_called_once()
