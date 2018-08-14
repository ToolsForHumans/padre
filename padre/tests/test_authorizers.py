import mock
import munch
from testtools import TestCase

from padre import authorizers as auth
from padre import exceptions as excp
from padre.tests import common


class AuthorizersTest(TestCase):
    def test_no_auth(self):
        bot = common.make_bot()
        message = mock.MagicMock()
        message.body = munch.Munch()
        a = auth.no_auth()
        a(bot, message)

    def test_or_auth(self):
        bot = common.make_bot()
        message = mock.MagicMock()
        message.body = munch.Munch()
        message.body.channel_name = 'not_my_channel'
        message.body.channel_id = 'not_my_channel'

        a = auth.message_from_channels(['my_channel'])
        self.assertRaises(excp.NotAuthorized, a, bot, message)

        b = a | auth.no_auth()
        b(bot, message)

    def test_and_auth(self):
        bot = common.make_bot()
        message = mock.MagicMock()
        message.body = munch.Munch()
        message.body.channel_name = 'not_my_channel'
        message.body.channel_id = 'not_my_channel'

        a = auth.no_auth()
        a(bot, message)

        b = a & auth.message_from_channels(['my_channel'])
        self.assertRaises(excp.NotAuthorized, b, bot, message)

    def test_user_in_ldap_groups(self):
        fake_ldap = mock.MagicMock()
        fake_ldap.is_allowed.return_value = True

        bot = common.make_bot()
        bot.config.my_group = 'abc'
        bot.clients.ldap_client = fake_ldap
        message = mock.MagicMock()
        message.body = munch.Munch()
        message.body.user_id = 'joe'
        message.body.user_name = 'joe'

        a = auth.user_in_ldap_groups('my_group')
        a(bot, message)
        fake_ldap.is_allowed.assert_called()

    def test_user_in_ldap_groups_bad(self):
        fake_ldap = mock.MagicMock()
        fake_ldap.is_allowed.return_value = False

        bot = common.make_bot()
        bot.config.my_group = 'abc'
        bot.clients.ldap_client = fake_ldap
        message = mock.MagicMock()
        message.body = munch.Munch()
        message.body.user_id = 'joe'
        message.body.user_name = 'joe'

        a = auth.user_in_ldap_groups('my_group')
        self.assertRaises(excp.NotAuthorized, a, bot, message)
        fake_ldap.is_allowed.assert_called()

    def test_message_from_channels(self):
        bot = common.make_bot()
        message = mock.MagicMock()
        message.body = munch.Munch()
        message.body.channel_name = 'my_channel'
        message.body.channel_id = 'my_channel'

        a = auth.message_from_channels(['my_channel'])
        a(bot, message)

    def test_message_from_channels_bad(self):
        bot = common.make_bot()

        message = mock.MagicMock()
        message.body = munch.Munch()
        message.body.channel_id = 'blah'
        message.body.channel_name = 'blah'

        a = auth.message_from_channels(['my_channel'])
        self.assertRaises(excp.NotAuthorized, a, bot, message)
