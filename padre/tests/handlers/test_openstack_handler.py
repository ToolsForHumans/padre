from testtools import TestCase

from padre import channel as c
from padre import handler
from padre.handlers import openstack
from padre.tests import common


class OpenStackHandlerTest(TestCase):
    def test_openstack_handles_messages(self):
        bot = common.make_bot()

        m = common.make_message(text="openstack server show", to_me=True)
        self.assertTrue(
            openstack.DescribeServerHandler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="openstack not server show", to_me=True)
        self.assertEqual(
            openstack.DescribeServerHandler.handles(m, c.TARGETED,
                                                    bot.config), None)

    def test_openstack_runs_default(self):
        bot = common.make_bot()
        bot.topo_loader.env_names = tuple(['test'])

        m = common.make_message(text="openstack server show",
                                to_me=True, user_id="me")
        h = openstack.DescribeServerHandler(bot, m)
        h.run(handler.HandlerMatch('blah-svrnm'))

        bot.topo_loader.load_one.assert_called()
