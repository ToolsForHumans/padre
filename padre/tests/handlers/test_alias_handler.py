from testtools import TestCase

from padre import channel as c
from padre import handler
from padre.handlers import alias
from padre.tests import common


class AliasHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = common.make_bot(simple_config=True)

        m = common.make_message(text="alias add b c", to_me=True)
        self.assertTrue(alias.AddHandler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="alias remove b c", to_me=True)
        self.assertTrue(alias.RemoveHandler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="alias clear", to_me=True)
        self.assertTrue(alias.ClearHandler.handles(m, c.TARGETED, bot.config))

    def test_add_alias(self):
        bot = common.make_bot(simple_config=True)

        m = common.make_message(text="alias add b c", to_me=True, user_id="me")
        h = alias.AddHandler(bot, m)
        h.run(handler.HandlerMatch("b c"))
        self.assertEqual(bot.brain.storage,
                         {'user:me': {'aliases': {'c': 'b'}}})

    def test_clear_alias(self):
        bot = common.make_bot(simple_config=True)
        bot.brain = common.MockBrain({
            'user:me': {'aliases': {'c': 'b', 'e': 'f'}},
        })

        m = common.make_message(text="alias clear", to_me=True, user_id="me")
        h = alias.ClearHandler(bot, m)
        h.run(handler.HandlerMatch())
        self.assertEqual(bot.brain.storage,
                         {'user:me': {'aliases': {}}})

    def test_remove_alias(self):
        bot = common.make_bot(simple_config=True)
        bot.brain = common.MockBrain({'user:me': {'aliases': {'c': 'b'}}})

        m = common.make_message(text="alias remove c",
                                to_me=True, user_id="me")
        h = alias.RemoveHandler(bot, m)
        h.run(handler.HandlerMatch("c"))
        self.assertEqual(bot.brain.storage,
                         {'user:me': {'aliases': {}}})
