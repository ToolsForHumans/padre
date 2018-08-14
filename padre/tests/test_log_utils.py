import logging

import mock
from testtools import TestCase

from padre import log_utils

LOG = logging.getLogger(__name__)


class LogUtilsTests(TestCase):
    def test_slack_triggered(self):
        slack_sender = mock.MagicMock()
        log = log_utils.SlackLoggerAdapter(LOG, slack_sender=slack_sender,
                                           ignore_levels=True,
                                           channel='fake')
        log.debug("Hello")
        slack_sender.post_send.assert_called()

    def test_slack_not_triggered(self):
        slack_sender = mock.MagicMock()
        log = log_utils.SlackLoggerAdapter(LOG, slack_sender=slack_sender,
                                           ignore_levels=True,
                                           channel='fake')
        log.debug("Hello", slack=False)
        slack_sender.post_send.assert_not_called()
