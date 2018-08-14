import mock
from testtools import TestCase

from padre import channel as c
from padre import event as e
from padre import handler
from padre.handlers import shutdown
from padre.tests import common


class ShutdownHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = common.make_bot()

        m = common.make_message(text="shutdown", to_me=True)
        self.assertTrue(shutdown.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="please, kill yourself",
                                to_me=True)
        self.assertEqual(
            shutdown.Handler.handles(m, c.TARGETED, bot.config), None)

    def test_shutdown(self):
        bot = common.make_bot()

        m = common.make_message(text="periodics run all",
                                to_me=True, user_id="me")

        h = shutdown.Handler(bot, m)
        with mock.patch('random.choice') as rch:
            rch.return_value = "Live long and prosper."
            h.run(handler.HandlerMatch())

        m.reply_text.assert_called_once_with(
            'Shutdown acknowledged. Live long and prosper.',
            prefixed=False, threaded=True)

        self.assertEqual(e.Event.DIE, bot.dead.value)
