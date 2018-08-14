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
    hook_path = "sensu-webhook"

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

    def hook(self, req):
        req_meth = req.method
        if req_meth.lower() != "post":
            LOG.warn("Received invalid sensu request"
                     " type/http method (not a POST)")
            raise exc.HTTPBadRequest
        content_type = req.content_type
        content_type = content_type.lower()
        if content_type != 'application/json':
            LOG.warn("Received invalid sensu content"
                     " type %s (not application/json)", content_type)
            raise exc.HTTPBadRequest
        try:
            data_len = int(req.content_length)
            if data_len <= 0:
                raise ValueError(
                    "Content length must be greater"
                    " than zero: got %s" % data_len)
        except ValueError:
            LOG.warn("Could not extract request content length",
                     exc_info=True)
            raise exc.HTTPBadRequest
        try:
            req_body = req.body_file.read(data_len)
        except IOError:
            LOG.warn("Could not read full POST body", exc_info=True)
            raise exc.HTTPBadRequest
        secret = self.bot.config.sensu.hook.get('secret', '')
        req_headers = req.headers
        try:
            if secret:
                wu.check_signature(req_headers.get('X-Padre-Signature'),
                                   req_body, secret)
        except (wu.NoSignature, wu.BadSignature):
            LOG.warn(
                "Received no/bad signature for"
                " body '%s'; headers=%s", req_body,
                req_headers, exc_info=True)
            raise exc.HTTPUnauthorized
        except wu.UnknownSignatureAlgorithm:
            LOG.warn(
                "Received unknown signature algorithm for"
                " body '%s'; headers=%s", req_body, req_headers,
                exc_info=True)
            raise exc.HTTPBadRequest
        try:
            req_body = json.loads(req_body.decode('utf-8'))
            if not isinstance(req_body, dict):
                raise TypeError(
                    "Expected dict type, did not"
                    " get it: got %s instead" % type(req_body))
        except (ValueError, TypeError, UnicodeError):
            LOG.warn(
                "Received bad/invalid json"
                " body '%s'", req_body, exc_info=True)
            raise exc.HTTPBadRequest
        else:
            try:
                event_action = req_body['action']
            except KeyError:
                LOG.warn("Received bad/invalid json"
                         " event body '%s' (missing event 'action')",
                         req_body, exc_info=True)
                raise exc.HTTPBadRequest
            if secret:
                LOG.debug("Received validated"
                          " sensu event (%s): %s", event_action, req_body)
            else:
                LOG.debug(
                    "Received not validated sensu event (%s): %s",
                    event_action, req_body)
            m_kind = 'sensu/%s' % event_action
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
    wsgi_port = bot.config.sensu.hook.port
    try:
        exposed = bot.config.sensu.hook.get('exposed', False)
    except AttributeError:
        exposed = False
    return wu.WSGIServerRunner(ssl_config, wsgi_app, wsgi_port,
                               exposed=exposed, max_workers=max_workers)
