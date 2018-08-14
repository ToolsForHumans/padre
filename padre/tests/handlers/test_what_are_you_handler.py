import mock
from testtools import TestCase

from padre import channel as c
from padre import handler
from padre.handlers import what_are_you
from padre.tests import common


class WhatAreYouHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = common.make_bot()

        m = common.make_message(text="what are you", to_me=True)
        self.assertTrue(
            what_are_you.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="what are you?", to_me=True)
        self.assertTrue(
            what_are_you.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="tell me what are you?",
                                to_me=True)
        self.assertEqual(
            what_are_you.Handler.handles(m, c.TARGETED, bot.config), None)

    @mock.patch('pkginfo.get_metadata')
    def test_info_without_metadata(self, get_meta):
        bot = common.make_bot()

        get_meta.return_value = False

        m = common.make_message(text="what are you?",
                                to_me=True, user_id="me")

        h = what_are_you.Handler(bot, m)
        h.run(handler.HandlerMatch())

        m.reply_text.assert_called_once_with(
            'I am not really sure what I am.',
            prefixed=False, threaded=True)

    def test_info_with_metadata(self):
        bot = common.make_bot()

        m = common.make_message(text="what are you?",
                                to_me=True, user_id="me")

        h = what_are_you.Handler(bot, m)
        with mock.patch('pkginfo.get_metadata'):
            h.run(handler.HandlerMatch())

        m.reply_text.assert_not_called()
        m.reply_attachments.assert_called_once()
