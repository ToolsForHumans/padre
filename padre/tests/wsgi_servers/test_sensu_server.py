import mock
import re
from testtools import TestCase, ExpectedException  # noqa

from padre import channel as c
from padre.tests import common
from padre.wsgi_servers import sensu

from webob import exc


class SensuHookApplicationTest(TestCase):
    def setUp(self):
        super(SensuHookApplicationTest, self).setUp()
        self.bot = common.make_bot()
        self.hook = sensu.HookApplication(self.bot)

    def test_creation(self):
        self.assertEqual(
            [(re.compile('^sensu-webhook[/]?(.*)$'),
              ['GET', 'POST'], self.hook.hook)],
            self.hook.urls
        )
        self.assertEqual(self.bot, self.hook.bot)

    def test_raised_with_wrong_env(self):
        with ExpectedException(TypeError, 'WSGI environ must be a dict;'):
            self.hook.__call__('env', 'resp')

    def test_raised_with_wrong_resp(self):
        env = dict()
        env['PATH_INFO'] = '.'
        with ExpectedException(TypeError, "'str' object is not callable"):
            self.hook.__call__(env, 'resp')

    @mock.patch('padre.wsgi_servers.sensu.Request')
    def test_magic_call(self, request):
        env = dict()
        env['PATH_INFO'] = '.'
        resp = mock.MagicMock()
        resp.path.lstrip.return_value = 'sensu-webhook'
        resp.method = 'GET'
        request.return_value = resp
        handler = mock.MagicMock()
        handler.return_value = lambda x, y: 'success, lol'
        self.hook.hook = handler
        re, meth, hook = self.hook.urls[0]
        self.hook.urls = [(re, meth, handler)]
        self.assertEqual('success, lol', self.hook.__call__(env, 'resp'))

    def test_hook_raises_with_bad_kind(self):
        req = mock.MagicMock()
        req.headers.get.return_value = None
        with ExpectedException(
                exc.HTTPBadRequest,
                'The server could not comply with the request'):
            self.hook.hook(req)

    def test_hook_raises_with_bad_request_type(self):
        req = mock.MagicMock()
        req.headers.get.side_effect = ['kind', '10']
        req.method = 'GET'
        with ExpectedException(
                exc.HTTPBadRequest,
                'The server could not comply with the request'):
            self.hook.hook(req)

    def test_hook_raises_with_wrong_content_type(self):
        req = mock.MagicMock()
        req.headers.get.side_effect = ['kind', '10']
        req.method = 'POST'
        req.content_type = 'text/html'
        with ExpectedException(
                exc.HTTPBadRequest,
                'The server could not comply with the request'):
            self.hook.hook(req)

    def test_hook_raises_with_zero_length(self):
        req = mock.MagicMock()
        req.headers.get.side_effect = ['kind', '10']
        req.method = 'POST'
        req.content_type = 'application/json'
        req.content_length = 0
        with ExpectedException(
                exc.HTTPBadRequest,
                'The server could not comply with the request'):
            self.hook.hook(req)

    def test_hook_raises_with_failed_network(self):
        req = mock.MagicMock()
        req.headers.get.side_effect = ['kind', '10']
        req.method = 'POST'
        req.content_type = 'application/json'
        req.content_length = 100
        req.body_file.read.side_effect = IOError('IO Error')

        with ExpectedException(
                exc.HTTPBadRequest,
                'The server could not comply with the request'):
            self.hook.hook(req)

    def test_hook_raises_with_empty_body(self):
        req = mock.MagicMock()
        req.headers.get.side_effect = ['kind', '10']
        req.method = 'POST'
        req.content_type = 'application/json'
        req.content_length = 100
        with ExpectedException(
                exc.HTTPBadRequest,
                'The server could not comply with the request'):
            self.hook.hook(req)

    def test_hook_successful_with_proper_data(self):
        req = mock.MagicMock()
        req.headers.get.side_effect = ['kind', '10']
        req.method = 'POST'
        req.content_type = 'application/json'
        req.content_length = 100
        req.body_file.read.return_value = ('{ "action": "create",'
                                           '"first": "data" }')
        self.assertEqual('202 Accepted', self.hook.hook(req).status)
        self.bot.submit_message.assert_any_call(mock.ANY, c.TARGETED)
        self.bot.submit_message.assert_any_call(mock.ANY, c.BROADCAST)

    def test_hook_raises_with_wrong_credentials(self):
        req = mock.MagicMock()
        req.headers.get.side_effect = ['kind', '10', 'signature']
        req.method = 'POST'
        req.content_type = 'application/json'
        req.content_length = 100
        self.bot.config.sensu.hook.secret = 'secret'
        with ExpectedException(
                exc.HTTPUnauthorized,
                'This server could not verify that you are authorized'):
            self.hook.hook(req)

    def test_hook_raises_with_wrong_body(self):
        req = mock.MagicMock()
        req.headers.get.side_effect = ['kind', '10', 'signature']
        req.method = 'POST'
        req.content_type = 'application/json'
        req.content_length = 100
        req.body_file.read.return_value = b'[ "test" ]'
        with ExpectedException(exc.HTTPBadRequest,
                               'The server could not comply with the request'):
            self.hook.hook(req)

    def test_hook_successful_if_message_not_sent(self):
        req = mock.MagicMock()
        req.headers.get.side_effect = ['kind', '10']
        req.method = 'POST'
        req.content_type = 'application/json'
        req.content_length = 100
        req.body_file.read.return_value = ('{ "action": "create",'
                                           '"first": "data" }')
        self.hook.bot.submit_message.side_effect = RuntimeError(
            'Error')
        self.assertEqual('202 Accepted', self.hook.hook(req).status)
        self.bot.submit_message.assert_called()
