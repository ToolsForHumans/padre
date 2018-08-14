import mock
from testtools import TestCase

from padre import channel as c
from padre import handler
from padre.handlers import ldap
from padre.tests import common


class LdapDescribeUserHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = common.make_bot()

        m = common.make_message(text="ldap describe user", to_me=True)
        self.assertTrue(
            ldap.DescribeUserHandler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="ldap do anything please",
                                to_me=True)
        self.assertEqual(
            ldap.DescribeUserHandler.handles(m, c.TARGETED, bot.config), None)

    def test_ldap_describe_nonexisting_user(self):
        bot = common.make_bot()

        ldap_client = mock.MagicMock()
        ldap_client.describe_user.return_value = False
        bot.clients.ldap_client = ldap_client

        m = common.make_message(text="ldap describe user",
                                to_me=True, user_id="me")

        h = ldap.DescribeUserHandler(bot, m)
        h.run(handler.HandlerMatch('NonExistentUser'))

        m.reply_text.assert_called_once_with(
            'No user with name `NonExistentUser` found.',
            prefixed=False, threaded=True)

    def test_ldap_describe_existing_user(self):
        bot = common.make_bot()
        ldap_client = mock.MagicMock()
        ldap_client.describe_user.return_value = {
            'name': 'Some User',
            'uid': 99999
        }
        bot.clients.ldap_client = ldap_client

        m = common.make_message(text="ldap describe user",
                                to_me=True, user_id="me")

        h = ldap.DescribeUserHandler(bot, m)
        h.run(handler.HandlerMatch('some_user'))

        m.reply_text.assert_called_once_with(
            u'```\nName         Uid\n---------  -----\nSome User  99999\n```',
            prefixed=False, threaded=True)


class LdapListUserHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = common.make_bot()

        m = common.make_message(text="ldap list", to_me=True)
        self.assertTrue(ldap.ListHandler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="ldap not list, lol", to_me=True)
        self.assertEqual(
            ldap.ListHandler.handles(m, c.TARGETED, bot.config), None)

    def test_ldap_list_nonexisting_group(self):
        bot = common.make_bot()
        ldap_client = mock.MagicMock()
        ldap_client.list_ldap_group.return_value = list()
        bot.clients.ldap_client = ldap_client

        m = common.make_message(text="ldap list",
                                to_me=True, user_id="me")

        h = ldap.DescribeUserHandler(bot, m)
        h.run(handler.HandlerMatch('NonExistentGroup'))

        m.reply_text.assert_called_once_with(u'```\n\n```', prefixed=False,
                                             threaded=True)

    def test_ldap_describe_existing_group(self):
        bot = common.make_bot()

        ldap_client = mock.MagicMock()
        ldap_client.list_ldap_group.return_value = [
            "DC=dc1,OU=AwesomeGroup,CN=dc_group"
        ]
        bot.clients.ldap_client = ldap_client

        m = common.make_message(text="ldap list", to_me=True, user_id="me")

        h = ldap.ListHandler(bot, m)
        h.run(handler.HandlerMatch('dc_group'))

        m.reply_text.assert_called_once_with(
            u'```\nCN        DC    OU\n--------  ----  ------------\n'
            u'dc_group  dc1   AwesomeGroup\n```',
            prefixed=False, threaded=True)
