import mock
import munch
from testtools import TestCase

from padre import channel as c
from padre import handler
from padre.handlers import dns
from padre.tests import common


class DNSHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = mock.MagicMock()
        bot.config = munch.Munch()

        m = common.make_message(text="dns lookup", to_me=True)
        self.assertTrue(dns.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="dns blahblah", to_me=True)
        self.assertEqual(dns.Handler.handles(m, c.TARGETED,
                                             bot.config), None)

    @mock.patch("padre.handlers.dns.socket.gethostbyname")
    def test_show_config(self, mock_gethostbyname):
        mock_gethostbyname.return_value = "1.2.3.4"
        bot = common.make_bot(simple_config=True)
        m = common.make_message(text="dns lookup blah.com",
                                to_me=True,
                                user_id="me")
        h = dns.Handler(bot, m)
        h.run(handler.HandlerMatch("blah.com"))

        m.reply_text.assert_called_once_with(
            'The ip address for `blah.com` is `1.2.3.4`',
            prefixed=False,
            threaded=True)
