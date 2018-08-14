import mock
import munch
from testtools import TestCase

from padre import channel as c
from padre.handlers import github as ghh
from padre.tests import common


class PRScanReportHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = mock.MagicMock()
        bot.config = munch.Munch()

        m = common.make_message(text="pull request report", to_me=True)
        self.assertTrue(ghh.PRScanReportHandler.handles(
            m, c.TARGETED, bot.config))

        m = common.make_message(text="help", to_me=True)
        self.assertFalse(ghh.PRScanReportHandler.handles(
            m, c.TARGETED, bot.config))
