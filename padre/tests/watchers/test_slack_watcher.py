import mock
from testtools import TestCase

from padre.tests import common
from padre.watchers import slack


class SlackWatcherTest(TestCase):
    def setUp(self):
        super(SlackWatcherTest, self).setUp()
        self.bot = common.make_bot()
        self.watcher = slack.Watcher(self.bot)

    def test_setup_lol(self):
        self.assertIsNone(self.watcher.setup())

    def test_run(self):
        slack_client = mock.MagicMock()
        self.watcher.bot.clients['slack_client'] = slack_client
        self.watcher.dead = mock.MagicMock()

        self.watcher.run()
        self.watcher.dead.is_set.return_value = True
