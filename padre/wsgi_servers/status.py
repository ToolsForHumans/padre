import copy
import errno
import functools
import logging
import os
import pkg_resources
import platform
import re
import socket
import sys
import threading
import traceback

import munch
from oslo_utils import reflection
from oslo_utils import strutils
import six
from tabulate import tabulate
from webob import exc
from webob import Request
from webob import Response

from padre import mixins
from padre import periodic_utils as pu
from padre import utils
from padre import wsgi_utils as wu

LOG = logging.getLogger(__name__)


def _get_threadstacks():
    # Taken from:
    # https://github.com/openstack/oslo.middleware/blob/master/\
    # oslo_middleware/healthcheck/__init__.py#L432 (and modified slightly...)
    threadstacks = []
    try:
        active_frames = dict(sys._current_frames())
    except AttributeError:
        pass
    else:
        try:
            buf = six.StringIO()
            for t_id, t_frame in six.iteritems(active_frames):
                traceback.print_stack(t_frame, file=buf)
                threadstacks.append({
                    'id': t_id,
                    'traceback': buf.getvalue(),
                })
                buf.seek(0)
                buf.truncate()
        finally:
            # NOTE: don't create GC loops...
            active_frames.clear()
    return threadstacks


def _introspect_environment():
    headers = [
        "Key", "Value",
    ]
    rows = []
    for k, v in utils.get_environ().items():
        rows.append([k, v])
    rows = sorted(rows, key=lambda v: v[0].lower())
    return rows, headers


def _introspect_system():
    headers = [
        "Key", "Value",
    ]
    rows = [
        [
            "Python version",
            sys.version,
        ],
        [
            "Platform",
            platform.platform(),
        ],
        [
            "Active threads",
            str(threading.active_count()),
        ],
    ]
    try:
        my_hostname = socket.gethostname()
    except socket.error:
        pass
    else:
        rows.append([
            "Hostname",
            my_hostname,
        ])
    rows = sorted(rows, key=lambda v: v[0].lower())
    return rows, headers


def _check_accepts(offers):

    def decorator(func):

        @six.wraps(func)
        def wrapper(self, req, *args, **kwargs):
            if not bool(req.accept.best_match(offers)):
                raise exc.HTTPNotAcceptable
            else:
                return func(self, req, *args, **kwargs)

        return wrapper

    return decorator


class StatusApplication(mixins.TemplateUser):
    def __init__(self, bot):
        self.urls = [
            (re.compile("^([/]*)$", re.I), ["GET"], self.reply_index)
        ]
        for v in ("status", "status.json"):
            v_r = r'^' + v + r'$'
            self.urls.append(
                (re.compile(v_r, re.I), ["GET"], self.reply_status))
        for v in ("config", "config.json"):
            v_r = r'^' + v + r'$'
            self.urls.append(
                (re.compile(v_r, re.I), ["GET"], self.reply_config))
        self.urls.append(
            (re.compile(r"^static/(.*)$", re.I), ["GET"], self.reply_static))
        for v in ("periodics", "periodics.json"):
            v_r = r'^' + v + r'$'
            self.urls.append(
                (re.compile(v_r, re.I), ["GET"], self.reply_periodics))
        try:
            log_file = bot.config.log_file
        except AttributeError:
            pass
        else:
            log_http_max_bytes = int(bot.config.get("log_http_max_bytes", -1))
            reply_func = functools.partial(
                self.reply_log, log_file, log_http_max_bytes)
            for v in ("log.txt", "logging.txt"):
                v_r = r'^' + v + r'$'
                self.urls.append((re.compile(v_r, re.I), ["GET"], reply_func))
        self.bot = bot
        self.template_dirs = list(bot.config.get('template_dirs', []))
        self.template_subdir = 'status'
        self.statics_dir = bot.config.statics_dir

    def __call__(self, environ, start_response):
        req = Request(environ)
        req_path = req.path.lstrip('/')
        handler = None
        handler_m = None
        for pat, ok_methods, maybe_handler in self.urls:
            m = pat.match(req_path)
            if not m:
                continue
            if req.method in ok_methods:
                handler = maybe_handler
                handler_m = m
                break
        try:
            if handler is None:
                raise exc.HTTPNotFound
            else:
                resp = handler(req, handler_m)
        except exc.HTTPError as e:
            return e.generate_response(environ, start_response)
        else:
            return resp(environ, start_response)

    def reply_log(self, log_file, log_http_max_bytes,
                  req, req_match):
        max_len = log_http_max_bytes
        try:
            all = strutils.bool_from_string(req.params['all'])
            if all:
                max_len = -1
        except KeyError:
            pass
        try:
            with open(log_file, 'rb') as fh:
                if max_len > 0:
                    _left_am, contents = utils.read_backwards_up_to(fh,
                                                                    max_len)
                elif max_len == 0:
                    contents = ''
                else:
                    contents = fh.read()
        except IOError as e:
            if e.errno == errno.ENOENT:
                # Likely not made yet, just send back nothing...
                contents = ''
            else:
                raise
        resp = Response()
        resp.status = 200
        resp.content_type = 'text/plain'
        try:
            contents_nl = contents.index("\n")
            resp.body = contents[contents_nl + 1:]
        except ValueError:
            resp.body = contents
        return resp

    def reply_static(self, req, req_match):
        path = req_match.group(1)
        # Ensure that the path isn't trying to do wild things like
        # escape out of our statics dir or such by just validating against
        # a basic regex...
        path_m = re.match(r"^[a-zA-Z0-9]+[.][a-zA-Z0-9]+$", path)
        if not path_m:
            raise exc.HTTPBadRequest
        static_path = os.path.join(self.statics_dir, path)
        if not os.path.isfile(static_path):
            raise exc.HTTPNotFound
        else:
            resp = Response()
            resp.status = 200
            with open(static_path, 'rb') as fh:
                resp.body = fh.read()
            _base, ext = os.path.splitext(static_path)
            ext = ext.lower()
            ext = ext.lstrip(".")
            if ext == 'ico':
                resp.content_type = 'image/x-icon'
            elif ext == "png":
                resp.content_type = 'image/png'
            elif ext == "html":
                resp.content_type = 'text/html'
            else:
                resp.content_type = 'application/binary'
            return resp

    @_check_accepts(['application/json'])
    def reply_periodics(self, req, req_match):
        sched_state, jobs = pu.format_scheduler(self.bot.scheduler)
        for i, job in enumerate(jobs):
            job = job.copy()
            if job.runs_in is not None:
                job.runs_in = utils.extract_elapsed(job.runs_in)
            jobs[i] = job
        resp = Response()
        resp.content_type = 'application/json'
        resp.status = 200
        resp_body = {
            'jobs': jobs,
            'scheduler_state': sched_state,
        }
        resp.body = utils.dump_json(resp_body, pretty=True) + "\n"
        return resp

    @_check_accepts(['text/html', 'application/xhtml+xml',
                     'application/xml', 'text/xml'])
    def reply_index(self, req, req_match):
        me = pkg_resources.get_distribution('padre')
        resp = Response()
        resp.content_type = 'text/html'
        resp.status = 200
        sys_table, sys_headers = _introspect_system()
        env_table, env_headers = _introspect_environment()
        resp.text = self.render_template("index.html", {
            'bot_app_version': me.version,
            'bot_app_name': me.key,
            'bot_name': self.bot.name,
            'sys_table': tabulate(sys_table, sys_headers, tablefmt='grid'),
            'env_table': tabulate(env_table, env_headers, tablefmt='grid'),
            'bot_config': self.bot.config,
            'threads': _get_threadstacks(),
        })
        return resp

    @_check_accepts(['application/json'])
    def reply_config(self, req, req_match):
        resp = Response()
        resp.content_type = 'application/json'
        resp.status = 200
        tmp_config = copy.deepcopy(self.bot.config)
        tmp_config = munch.unmunchify(tmp_config)
        tmp_config = utils.mask_dict_password(tmp_config)
        resp_body = tmp_config
        resp_body = utils.dump_json(resp_body, pretty=True)
        resp.body = resp_body + "\n"
        return resp

    @_check_accepts(['application/json'])
    def reply_status(self, req, req_match):
        def _format_handler(h):
            h_cls_name = reflection.get_class_name(h)
            h_elapsed = None
            try:
                h_elapsed = h.watch.elapsed()
            except RuntimeError:
                pass
            return {
                'class': h_cls_name,
                'state': h.state,
                'state_history': list(h.state_history),
                'elapsed': h_elapsed,
                'message': h.message.to_dict(),
                'created_on': h.created_on,
            }
        resp = Response()
        resp.content_type = 'application/json'
        resp.status = 200
        resp_body = {}
        started_at = self.bot.started_at
        if started_at is None:
            resp_body['uptime'] = {}
        else:
            now = self.bot.date_wrangler.get_now()
            diff = now - started_at
            elapsed = utils.extract_elapsed(diff.total_seconds())
            resp_body['uptime'] = dict(elapsed)
        active_handlers = []
        for h in list(self.bot.active_handlers):
            active_handlers.append(_format_handler(h))
        stats = {}
        for h_cls in list(self.bot.handlers):
            h_cls_stats = h_cls.stats
            h_cls_name = reflection.get_class_name(h_cls)
            stats[h_cls_name] = dict(h_cls_stats)
        prior_handlers = {}
        with self.bot.locks.prior_handlers:
            for c, ch_handlers in self.bot.prior_handlers.items():
                tmp_c = c.name.lower()
                prior_handlers[tmp_c] = {}
                for k, k_handlers in ch_handlers.items():
                    tmp_handlers = []
                    prior_handlers[tmp_c][k] = tmp_handlers
                    for h in list(k_handlers):
                        tmp_handlers.append(_format_handler(h))
        resp_body['handlers'] = {
            'stats': stats,
            'active': active_handlers,
            'prior': prior_handlers,
        }
        resp_body['clients'] = []
        for client_name in sorted(self.bot.clients.keys()):
            # TODO: fix this in the other file so that we can just use
            # the actual keys...
            if client_name.endswith("_client"):
                client_name = client_name[0:-len("_client")]
            resp_body['clients'].append(client_name)
        resp_body['wsgi_servers'] = sorted(self.bot.wsgi_servers.keys())
        resp_body['watchers'] = sorted(self.bot.watchers.keys())
        with self.bot.locks.channel_stats:
            resp_body['channel_stats'] = {}
            for c, c_stats in self.bot.channel_stats.items():
                tmp_c = c.name.lower()
                resp_body['channel_stats'][tmp_c] = copy.deepcopy(c_stats)
        resp_body = utils.dump_json(resp_body, pretty=True)
        resp.body = resp_body + "\n"
        return resp


def create_server(bot, max_workers):
    ssl_config = munch.Munch()
    try:
        if bot.config.status.get("ssl"):
            ssl_config = bot.config.get("ssl", munch.Munch())
    except AttributeError:
        pass
    wsgi_app = StatusApplication(bot)
    wsgi_port = bot.config.status.port
    try:
        exposed = bot.config.status.get('exposed', False)
    except AttributeError:
        exposed = False
    return wu.WSGIServerRunner(ssl_config, wsgi_app, wsgi_port,
                               exposed=exposed, max_workers=max_workers)
