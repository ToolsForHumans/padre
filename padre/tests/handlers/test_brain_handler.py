from testtools import TestCase

from padre import channel as c
from padre.handlers import brain
from padre.tests import common


class BrainHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = common.make_bot(simple_config=True)

        m = common.make_message(text="brain dump bob", to_me=True)
        self.assertTrue(brain.DumpHandler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="brain no list", to_me=True)
        self.assertFalse(brain.DumpHandler.handles(m, c.TARGETED, bot.config))
