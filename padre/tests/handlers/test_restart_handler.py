from testtools import TestCase

from padre import channel as c
from padre import event as e
from padre import handler
from padre.handlers import restart
from padre.tests import common


class RestartHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = common.make_bot()

        m = common.make_message(text="restart", to_me=True)
        self.assertTrue(
            restart.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="not restart", to_me=True)
        self.assertEqual(
            restart.Handler.handles(m, c.TARGETED, bot.config), None)

    def test_restart_get_message(self):
        bot = common.make_bot()

        m = common.make_message(text="restart",
                                to_me=True, user_id="me")

        h = restart.Handler(bot, m)
        h.run(handler.HandlerMatch())

        m.reply_text.assert_called_once_with(
            'Restart acknowledged. Be back in a bit!',
            prefixed=False, threaded=True)

    def test_restart_check_bot_really_restarted(self):
        bot = common.make_bot()

        m = common.make_message(text="restart",
                                to_me=True, user_id="me")

        h = restart.Handler(bot, m)
        h.run(handler.HandlerMatch())

        self.assertEqual(e.Event.RESTART, bot.dead.value)
