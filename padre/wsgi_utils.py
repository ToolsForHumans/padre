import hashlib
import hmac
import logging
import multiprocessing
import ssl
import threading

import futurist
import six
from wsgiref import simple_server

from oslo_utils import reflection

from padre import utils

LOG = logging.getLogger(__name__)


class NoSignature(Exception):
    pass


class UnknownSignatureAlgorithm(Exception):
    pass


class BadSignature(Exception):
    pass


def check_signature(header, blob, secret):
    if not header:
        raise NoSignature
    try:
        algo_name, signature = header.split('=', 1)
        algo_name = algo_name.lower().strip()
    except ValueError:
        raise NoSignature
    if isinstance(secret, six.text_type):
        secret = secret.encode("utf8")
    if algo_name == 'sha1':
        mac = hmac.new(secret, digestmod=hashlib.sha1)
    elif algo_name == 'sha224':
        mac = hmac.new(secret, digestmod=hashlib.sha224)
    elif algo_name == 'sha256':
        mac = hmac.new(secret, digestmod=hashlib.sha256)
    elif algo_name == 'sha384':
        mac = hmac.new(secret, digestmod=hashlib.sha384)
    elif algo_name == 'sha512':
        mac = hmac.new(secret, digestmod=hashlib.sha512)
    elif algo_name == 'md5':
        mac = hmac.new(secret, digestmod=hashlib.md5)
    else:
        tmp_algo_name = algo_name[0:10]
        if len(algo_name) > 10:
            tmp_algo_name += "..."
        raise UnknownSignatureAlgorithm(
            "Unknown algorithm '%s'" % tmp_algo_name)
    mac.update(blob)
    expected_signature = mac.hexdigest()
    ok = hmac.compare_digest(expected_signature, signature)
    if not ok:
        raise BadSignature


class WSGIServer(simple_server.WSGIServer):
    def __init__(self, server_address, request_handler_cls, executor):
        simple_server.WSGIServer.__init__(self, server_address,
                                          request_handler_cls)
        self.executor = executor

    def handle_error(self, request, client_address, exc_info=None):
        LOG.warn("Exception happened during processing"
                 " of request from %s", client_address,
                 exc_info=exc_info)

    def process_request(self, request, client_address):

        def _run_request(request, client_address):
            self.finish_request(request, client_address)
            self.shutdown_request(request)

        def _on_done(fut):
            try:
                fut.result()
            except Exception:
                self.handle_error(fut.request, fut.client_address,
                                  exc_info=True)
                self.shutdown_request(fut.request)

        fut = self.executor.submit(_run_request, request, client_address)
        fut.request = request
        fut.client_address = client_address
        fut.add_done_callback(_on_done)


class WSGIRequestHandler(simple_server.WSGIRequestHandler):
    def log_request(self, code='-', size='-'):
        LOG.log(utils.TRACE,
                'Received http/https request: "%s" %s %s',
                self.requestline, str(code), str(size))

    def log_error(self, format, *args):
        LOG.warn(format, *args)


class WSGIServerRunner(threading.Thread):
    def __init__(self, ssl_config, wsgi_app, port,
                 exposed=False, max_workers=None):
        super(WSGIServerRunner, self).__init__()
        self.ssl_config = ssl_config
        self.port = port
        self.exposed = exposed
        self.daemon = True
        self.wsgi_app = wsgi_app
        self.server = None
        self.executor = None
        if max_workers is None:
            try:
                max_workers = multiprocessing.cpu_count()
            except NotImplementedError:
                max_workers = 1
        self.max_workers = max_workers

    def setup(self):
        bind_port = self.port
        if self.exposed:
            bind_addr = '0.0.0.0'
        else:
            bind_addr = 'localhost'
        try:
            keyfile = self.ssl_config.private_key.path
        except AttributeError:
            keyfile = None
        try:
            certfile = self.ssl_config.cert.path
        except AttributeError:
            certfile = None
        executor = futurist.ThreadPoolExecutor(max_workers=self.max_workers)
        server = make_server(bind_addr, bind_port, self.wsgi_app,
                             executor, certfile=certfile, keyfile=keyfile)
        if keyfile or certfile:
            server_base = 'https'
        else:
            server_base = 'http'
        server_host, server_port = server.server_address
        for pat, ok_methods, _maybe_handler in getattr(self.wsgi_app,
                                                       'urls', []):
            LOG.info("Will match %s requests that match pattern"
                     " '%s' on port %s on %s://%s for app: %s (dispatching"
                     " into a worker pool/executor of size %s)",
                     ", ".join(sorted(ok_methods)), pat.pattern,
                     server_port, server_base, server_host,
                     reflection.get_class_name(self.wsgi_app),
                     self.max_workers)
        self.server = server
        self.executor = executor
        self._server_base = server_base
        self._server_port = server_port

    def shutdown(self):
        if self.executor is not None:
            self.executor.shutdown()
            self.executor = None
        if self.server is not None:
            self.server.shutdown()
            self.server = None

    def run(self):
        tmp_server = self.server
        if tmp_server is not None:
            tmp_server.serve_forever()


def make_server(host, port, wsgi_app, executor,
                certfile=None, keyfile=None):
    server = WSGIServer((host, port), WSGIRequestHandler, executor)
    server.set_app(wsgi_app)
    if certfile or keyfile:
        server.socket = ssl.wrap_socket(server.socket,
                                        server_side=True,
                                        certfile=certfile,
                                        keyfile=keyfile)
    return server
