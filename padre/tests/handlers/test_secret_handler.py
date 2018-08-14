import mock
import munch
from testtools import TestCase

from padre import handler


class DummyHandler(handler.Handler):
    def _run(self):
        pass


class Dummy2Handler(handler.Handler):
    secret_section = 'blah'

    def _run(self):
        pass


class DummySecretHandlerTest(TestCase):
    def test_enabled_no_secrets(self):
        bot = mock.MagicMock()
        bot.config = munch.Munch()
        bot.secrets = munch.Munch()
        self.assertTrue(DummyHandler.is_enabled(bot))

    def test_not_enabled_secrets(self):
        bot = mock.MagicMock()
        bot.config = munch.Munch()
        bot.secrets = munch.Munch()
        self.assertFalse(Dummy2Handler.is_enabled(bot))
