import mock
import munch
from testtools import TestCase

from padre import channel as c
from padre import handler
from padre.handlers import version
from padre.tests import common


class VersionHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = common.make_bot()

        m = common.make_message(text="version", to_me=True)
        self.assertTrue(version.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="vrsn", to_me=True)
        self.assertEqual(
            version.Handler.handles(m, c.TARGETED, bot.config), None)

    @mock.patch('pkg_resources.get_distribution')
    def test_version_without_distribution(self, get_dist):
        bot = common.make_bot()

        get_dist.return_value = False

        m = common.make_message(text="version",
                                to_me=True, user_id="me")

        h = version.Handler(bot, m)
        h.run(handler.HandlerMatch())

        m.reply_text.assert_called_once_with(
            'I am not really sure what version I am.',
            prefixed=False, threaded=True)

    @mock.patch('pkg_resources.get_distribution')
    def test_version_with_distribution(self, get_dist):
        bot = common.make_bot()

        get_dist.return_value = munch.Munch({'version': '1.0.0'})

        m = common.make_message(text="version",
                                to_me=True, user_id="me")

        h = version.Handler(bot, m)
        h.run(handler.HandlerMatch())

        m.reply_text.assert_called_once_with(
            'I am padre version `1.0.0`.',
            prefixed=False, threaded=True)
