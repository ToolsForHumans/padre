import json
import logging
import re

import munch

from webob import exc
from webob import Request
from webob import Response

from padre import channel as c
from padre import finishers
from padre import message
from padre import wsgi_utils as wu

LOG = logging.getLogger(__name__)


class HookApplication(object):
    hook_path = "github-webhook"
    pong_response = json.dumps({'msg': 'pong'}, indent=4)

    def __init__(self, bot):
        self.urls = [
            # Order matters.
            (re.compile(r'^' + self.hook_path + r'[/]?(.*)$'),
             ["GET", "POST"], self.hook),
        ]
        self.bot = bot

    def __call__(self, environ, start_response):
        req = Request(environ)
        req_path = req.path.lstrip('/')
        req_meth = req.method
        handler = None
        for pat, ok_methods, maybe_handler in self.urls:
            if pat.match(req_path) and req_meth in ok_methods:
                handler = maybe_handler
                break
        try:
            if handler is None:
                raise exc.HTTPNotFound
            else:
                resp = handler(req)
        except exc.HTTPError as e:
            return e.generate_response(environ, start_response)
        else:
            return resp(environ, start_response)

    def reply_pong(self, req):
        resp = Response()
        resp.content_type = 'application/json'
        resp.status = 200
        resp.body = self.pong_response + "\n"
        return resp

    def hook(self, req):
        kind = req.headers.get('X-GitHub-Event', '')
        delivery_id = req.headers.get("X-Github-Delivery", '')
        if delivery_id:
            delivery_id = delivery_id.strip()
        if kind:
            kind = kind.strip()
        if not kind or not delivery_id:
            raise exc.HTTPBadRequest
        if kind == 'ping':
            return self.reply_pong(req)
        req_meth = req.method
        if req_meth != "POST":
            raise exc.HTTPBadRequest
        content_type = req.content_type
        content_type = content_type.lower()
        if content_type != 'application/json':
            raise exc.HTTPBadRequest
        try:
            data_len = int(req.content_length)
            if data_len <= 0:
                raise ValueError
        except ValueError:
            raise exc.HTTPBadRequest
        try:
            req_body = req.body_file.read(data_len)
        except IOError:
            raise exc.HTTPBadRequest
        secret = self.bot.config.github.hook.get('secret', '')
        try:
            if secret:
                wu.check_signature(req.headers.get('X-Hub-Signature'),
                                   req_body, secret)
        except (wu.NoSignature, wu.BadSignature):
            LOG.debug(
                "Received no/bad signature for delivery id '%s' with"
                " body '%s'", delivery_id, req_body)
            raise exc.HTTPUnauthorized
        except wu.UnknownSignatureAlgorithm:
            raise exc.HTTPBadRequest
        try:
            req_body = json.loads(req_body.decode('utf-8'))
            if not isinstance(req_body, dict):
                raise ValueError
        except (ValueError, TypeError, UnicodeError):
            raise exc.HTTPBadRequest
        else:
            m_kind = 'github/%s' % kind
            m_headers = {
                message.VALIDATED_HEADER: bool(secret),
                message.TO_ME_HEADER: True,
                message.CHECK_AUTH_HEADER: False,
            }
            m_body = munch.munchify(req_body)
            m = message.Message(m_kind, m_headers, m_body)
            try:
                self.bot.submit_message(m, c.BROADCAST)
                fut = self.bot.submit_message(m, c.TARGETED)
                fut.add_done_callback(
                    finishers.log_on_fail(self.bot, m, log=LOG))
            except RuntimeError:
                pass
            resp = Response()
            resp.status = 202
            return resp


def create_server(bot, max_workers):
    ssl_config = bot.config.get("ssl", munch.Munch())
    wsgi_app = HookApplication(bot)
    wsgi_port = bot.config.github.hook.port
    try:
        exposed = bot.config.github.hook.get('exposed', False)
    except AttributeError:
        exposed = False
    return wu.WSGIServerRunner(ssl_config, wsgi_app, wsgi_port,
                               exposed=exposed, max_workers=max_workers)
