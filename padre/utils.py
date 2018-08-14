import collections
import contextlib
import datetime
import errno
import hashlib
import inspect
import json
import keyword
import logging
import os
import re
import shlex
import shutil
import sys
import tempfile

import futurist
import jinja2
import munch
import six
import yaml

from six.moves import zip as compat_zip

from oslo_utils import importutils
from oslo_utils import reflection
from oslo_utils import strutils
from oslo_utils import timeutils
import paho.mqtt.client as mqtt

from padre import exceptions as excp

SECRETE = '***'
TRACE = 5
LOG = logging.getLogger(__name__)
NAUGHTY_SINGLE_QUOTES = tuple([
    u"\u2018",
    u"\u2019",
])
NAUGHTY_DOUBLE_QUOTES = tuple([
    u"\u201c",
    u"\u201d",
])
NAUGHTY_ENV_KEYS = tuple([
    'DEPLOY_PASS', 'DADDY_PASS',
    'SECRETS_PASS', 'JENKINS_TOKEN',
])
BASE_ELAPSED = munch.Munch({
    'weeks': 0,
    'days': 0,
    'hours': 0,
    'years': 0,
    'minutes': 0,
    'seconds': 0,
})


def camel_to_underscore(camel_text):

    def _replacer(m):
        return m.group(1) + "_" + m.group(2).lower() + m.group(3)

    def _replacer2(m):
        return m.group(1) + "_" + m.group(2).lower()

    text = re.sub(r"(.)([A-Z])([a-z]+)", _replacer, camel_text)
    return re.sub(r"([a-z0-9])([A-Z]+)", _replacer2, text)


def quote_join(items, quote_char="'", join_chars=", "):
    tmp_items = []
    for item in items:
        tmp_items.append(quote_char + str(item) + quote_char)
    return join_chars.join(tmp_items)


def to_ordinal(n):
    if n <= 0:
        raise ValueError("Can not turn %s into an ordinal" % n)
    d = n % 10
    if (d == 1 and (n < 10 or n > 20)):
        return "%sst" % n
    elif (d == 2 and (n < 10 or n > 20)):
        return "%snd" % n
    elif (d == 3 and (n < 10 or n > 20)):
        return "%srd" % n
    else:
        return "%sth" % n


def dump_json(obj, pretty=False):
    def _default(obj):
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        elif inspect.isclass(obj):
            return reflection.get_class_name(obj)
        elif isinstance(obj, (set, frozenset)):
            return list(sorted(obj))
        else:
            raise TypeError("Type '%r' is not JSON serializable" % (obj,))
    if pretty:
        return json.dumps(obj, indent=4, default=_default, sort_keys=True)
    else:
        return json.dumps(obj, default=_default)


def merge_dict(config, more_config, prefer_latter=True):
    if more_config is None:
        return config
    out_config = {}
    for k in config.keys():
        if k not in more_config:
            out_config[k] = config[k]
        else:
            v1 = config[k]
            v2 = more_config[k]
            if isinstance(v1, dict) and isinstance(v2, dict):
                out_config[k] = merge_dict(v1, v2,
                                           prefer_latter=prefer_latter)
            else:
                if prefer_latter:
                    out_config[k] = v2
                else:
                    out_config[k] = v1
    for k in more_config.keys():
        if k not in out_config:
            out_config[k] = more_config[k]
    return out_config


def hash_pieces(pieces, algo="md5", max_len=-1):
    hasher = hashlib.new(algo)
    for piece in pieces:
        if piece is None:
            continue
        if isinstance(piece, six.text_type):
            piece = piece.encode("utf8")
        hasher.update(piece)
    d = hasher.hexdigest()
    if max_len != -1:
        d = d[0:max_len]
    return d


def cycle_from_item(items, item=None):
    item_idx = -1
    if item is not None:
        try:
            item_idx = items.index(item)
        except ValueError:
            pass
    if item_idx == -1:
        for item in items:
            yield item
    else:
        before_items = items[0:item_idx]
        items = items[item_idx:]
        for item in items:
            yield item
        for item in before_items:
            yield item


def iter_sorted_items(a_dict):
    for k in sorted(six.iterkeys(a_dict)):
        yield k, a_dict[k]


def get_environ():
    """Small helper (mainly for mocking/testing/cutting out keys usage)."""
    env = os.environ.copy()
    for k in NAUGHTY_ENV_KEYS:
        env.pop(k, None)
    for k in list(env.keys()):
        if k.startswith("_"):
            env.pop(k, None)
    return env


def mask_dict_password(config):
    # Adds a few more filters ontop of the strutils version...
    tmp_config = strutils.mask_dict_password(config)
    if 'ssl' in tmp_config:
        for k in list(tmp_config['ssl'].keys()):
            v = tmp_config['ssl'].get(k, {})
            if v and 'contents' in v:
                v['contents'] = SECRETE
    if 'ssh' in tmp_config:
        for k in ['private_key', 'public_key']:
            if k in tmp_config['ssh']:
                tmp_config['ssh'][k] = SECRETE
    if 'stock' in tmp_config:
        for k in list(tmp_config['stock'].keys()):
            tmp_config['stock'][k] = SECRETE
    if 'google_calendar' in tmp_config:
        for k in ["credentials"]:
            tmp_config['google_calendar'][k] = SECRETE
    return tmp_config


def safe_make_dirs(path):
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno in (errno.EISDIR, errno.EEXIST):
            if e.errno == errno.EEXIST and not os.path.isdir(path):
                raise
            pass
        else:
            raise


def to_bytes(blob, encode_as='utf8'):
    if isinstance(blob, six.binary_type):
        return blob
    return blob.encode(encode_as)


def is_short(text):
    # For slack fields...
    return len(text) <= 15


def format_bytes(bytes_am, quote=False):
    kb_am = bytes_am / 1000
    mb_am = float(kb_am) / 1000
    gb_am = float(mb_am) / 1000
    result = "%0.2fMB/%0.2fGB" % (mb_am, gb_am)
    if quote:
        result = "`" + result + "`"
    return result


def format_seconds(seconds):
    m = extract_elapsed(seconds)
    m_pieces = []
    for k in ('years', 'weeks', 'days', 'hours', 'minutes'):
        v = m[k]
        if v == 0:
            continue
        if v == 1:
            k = k[0:-1]
        m_pieces.append("%s %s" % (v, k))
    if m.seconds > 0 or len(m_pieces) == 0:
        if m.seconds == 1:
            m_pieces.append("%s second" % m.seconds)
        else:
            m_pieces.append("%s seconds" % m.seconds)
    m_buf = six.StringIO()
    if len(m_pieces) > 2:
        m_buf.write(", ".join(m_pieces[0:-1]))
        m_buf.write(" and ")
        m_buf.write(m_pieces[-1])
    elif len(m_pieces) == 2:
        m_buf.write(" and ".join(m_pieces))
    else:
        m_buf.write(m_pieces[0])
    return m_buf.getvalue()


def extract_elapsed(seconds):
    if not isinstance(seconds, six.integer_types):
        seconds = int(seconds)
    m = BASE_ELAPSED.copy()
    # TODO: maybe throw a error instead of max(0, secs_elapsed)??
    m.seconds = max(0, seconds)
    if m.seconds >= 60:
        m.minutes, m.seconds = divmod(m.seconds, 60)
        if m.minutes >= 60:
            m.hours, m.minutes = divmod(m.minutes, 60)
            if m.hours >= 24:
                m.days, m.hours = divmod(m.hours, 24)
                if m.days >= 7:
                    m.weeks, m.days = divmod(m.days, 7)
                    if m.weeks >= 52:
                        m.years, m.weeks = divmod(m.weeks, 52)
    return m


@contextlib.contextmanager
def make_tmp_dir(*args, **kwargs):
    a_dir = tempfile.mkdtemp(*args, **kwargs)
    if not a_dir.endswith(os.path.sep):
        a_dir += os.path.sep
    try:
        yield a_dir
    finally:
        shutil.rmtree(a_dir)


def dict_or_munch_extract(root, path):
    if not path:
        raise ValueError("At least one dot separated component "
                         "must be provided")
    path_pieces = path.split(".")
    while len(path_pieces) > 1:
        root_key = path_pieces.pop(0)
        if not isinstance(root, dict):
            raise TypeError("Can not extract key '%s'"
                            " from non-dict" % root_key)
        root = root[root_key]
    root_key = path_pieces[0]
    if not isinstance(root, dict):
        raise TypeError("Can not extract key '%s'"
                        " from non-dict" % root_key)
    return root[root_key]


def pos_int(val, zero_ok=False):
    if not isinstance(val, six.integer_types):
        tmp_val = int(val)
    else:
        tmp_val = val
    if tmp_val <= 0 and not zero_ok:
        raise ValueError("Value '%s' must be greater than zero" % val)
    if tmp_val < 0 and zero_ok:
        raise ValueError("Value '%s' must be greater"
                         " than or equal to zero" % val)
    return tmp_val


def is_likely_kwarg(maybe_kwarg):
    if maybe_kwarg.find("=") == -1:
        return False
    arg, _arg_val = maybe_kwarg.split("=", 1)
    # Ensure the potential keyword argument is a valid
    # python variable name...
    if keyword.iskeyword(arg):
        return False
    if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", arg):
        return True
    return False


def extract_args(args, args_order,
                 args_converters=None, args_defaults=None,
                 allow_extras=False, args_accumulate=None):
    if isinstance(args, (six.string_types)):
        # Because OSX can do this, and it will bust shlex splitting.
        for c in NAUGHTY_DOUBLE_QUOTES:
            args = args.replace(c, '"')
        for c in NAUGHTY_SINGLE_QUOTES:
            args = args.replace(c, "'")
        arg_pieces = shlex.split(args)
    elif isinstance(args, (list, tuple)):
        arg_pieces = []
        for a in args:
            if not isinstance(a, (six.string_types)):
                a = str(a)
            arg_pieces.append(a)
    else:
        raise TypeError("Expected string or"
                        " list/tuple, not %s" % type(args))

    if args_converters is None:
        args_converters = {}
    if args_defaults is None:
        args_defaults = {}
    if args_accumulate is None:
        args_accumulate = set()

    maybe_args = []
    maybe_kwargs = []
    for i, arg in enumerate(arg_pieces):
        if is_likely_kwarg(arg):
            maybe_kwargs.append(i)
        else:
            maybe_args.append(i)

    if maybe_args and maybe_kwargs:
        # It's easier to just not allow intermixing then trying to
        # determine and especially *reason* about the order of
        # intermixed positional arguments and keyword arguments...
        #
        # So ya, just die if they are likely intermixed...
        min_kwarg_idx = min(maybe_kwargs)
        max_arg_idx = max(maybe_args)
        min_arg_idx = min(maybe_args)
        if min_kwarg_idx < min_arg_idx or max_arg_idx > min_kwarg_idx:
            raise excp.ArgumentError(
                "Keyword arguments must always follow"
                " positional arguments (and not be"
                " intermixed)")

    in_kwargs = collections.defaultdict(list)
    in_kwargs_order = []
    in_pos_args = []
    for i in maybe_args:
        in_pos_args.append(arg_pieces[i])
    for i in maybe_kwargs:
        arg, arg_val = arg_pieces[i].split("=", 1)
        in_kwargs[arg].append(arg_val)
        in_kwargs_order.append(arg)

    if len(in_pos_args) > len(args_order):
        if not allow_extras:
            num_extra_args = len(in_pos_args) - len(args_order)
            raise excp.ArgumentError(
                "%s extra (and unexpected)"
                " positional arguments were provided" % num_extra_args)

    out_args = collections.OrderedDict()
    for arg_name, arg_value in compat_zip(args_order, in_pos_args):
        if arg_name in args_accumulate:
            out_args[arg_name] = [arg_value]
        else:
            out_args[arg_name] = arg_value

    for arg_name in in_kwargs_order:
        if arg_name not in args_order:
            if not allow_extras:
                raise excp.ArgumentError(
                    "Unknown keyword argument '%s' provided" % (arg_name))
        arg_values = in_kwargs[arg_name]
        if arg_name in args_accumulate:
            if arg_name in out_args:
                existing_arg_values = out_args[arg_name]
                existing_arg_values.extend(arg_values)
            else:
                out_args[arg_name] = list(arg_values)
        else:
            out_args[arg_name] = arg_values[-1]

    for arg_name in args_order:
        try:
            arg_value = out_args[arg_name]
        except KeyError:
            if arg_name in args_defaults:
                if arg_name in args_accumulate:
                    out_args[arg_name] = [args_defaults[arg_name]]
                else:
                    out_args[arg_name] = args_defaults[arg_name]

    for arg_name in list(six.iterkeys(out_args)):
        arg_value = out_args[arg_name]
        arg_converter = args_converters.get(arg_name)
        if arg_converter is not None:
            if arg_name in args_accumulate:
                for i, i_arg_value in enumerate(arg_value):
                    arg_value[i] = arg_converter(i_arg_value)
            else:
                out_args[arg_name] = arg_converter(arg_value)

    return out_args


def only_one_of(allowed, value):
    if value not in allowed:
        ok_to_use = ", ".join(allowed)
        raise ValueError(
            "Only one of [%s] is allowed, not '%s'" % (ok_to_use, value))
    return value


def iter_chunks(items, chunk_size):
    if chunk_size <= 0:
        raise ValueError("Chunk size must be greater than zero")
    items_it = iter(items)
    batch = []
    while True:
        try:
            item = six.next(items_it)
        except StopIteration:
            break
        else:
            batch.append(item)
            if len(batch) >= chunk_size:
                yield batch
                batch = []
    if len(batch):
        yield batch
        batch = []


def read_backwards_up_to_chop(fh, max_bytes):
    left, contents = read_backwards_up_to(fh, max_bytes)
    if left:
        tmp_contents = "%s more..." % left
        tmp_contents += " " + contents
        contents = tmp_contents
    return contents


def read_backwards_up_to(fh, max_bytes):
    fh.seek(0, os.SEEK_END)
    fh_size = fh.tell()
    fh.seek(0, os.SEEK_SET)
    if max_bytes == 0:
        return (fh_size, '')
    if fh_size <= max_bytes:
        return (0, fh.read())
    else:
        seek_to = fh_size - max_bytes
        fh.seek(seek_to, os.SEEK_SET)
        return (seek_to, fh.read())


def find_executable(what, sys_bin_path=None):
    maybe_bin_paths = []
    if not sys_bin_path:
        sys_bin_path = os.getenv("PATH")
    if sys_bin_path:
        maybe_bin_paths.extend(sys_bin_path.split(os.pathsep))
    py_bin_dir = os.path.dirname(sys.executable)
    if py_bin_dir not in maybe_bin_paths:
        maybe_bin_paths.insert(0, py_bin_dir)
    what_bin = None
    for bin_path in maybe_bin_paths:
        bin_path = bin_path.strip()
        if not bin_path:
            continue
        try:
            bin_contents = os.listdir(bin_path)
        except OSError as e:
            if e.errno in (errno.ENOENT, errno.ENOTDIR):
                bin_contents = []
            else:
                raise
        if what in bin_contents:
            what_path = os.path.join(bin_path, what)
            if os.path.isfile(what_path) and os.access(what_path, os.X_OK):
                what_bin = what_path
                break
    return what_bin


def can_find_all_executables(cmds, logger=None, log_level=logging.WARNING):
    seen_cmds = set()
    missing_cmds = set()
    for cmd in cmds:
        if cmd in seen_cmds:
            continue
        cmd_bin = find_executable(cmd)
        if not cmd_bin:
            if logger is not None:
                logger.log(log_level,
                           "Required command '%s' was not found", cmd)
            missing_cmds.add(cmd)
        seen_cmds.add(cmd)
    if len(missing_cmds):
        return False
    return True


def canonicalize_text(message_text):
    message_text = message_text.strip()
    message_text = message_text.lower()
    return message_text


def make_mqtt_client(config, topics=None,
                     max_connect_wait=10, check_delay=0.01,
                     log=None):
    if log is None:
        log = LOG

    fut = futurist.Future()
    fut.set_running_or_notify_cancel()
    firehose_port = config.firehose_port
    if not topics:
        topics = set(["#"])
    else:
        topics = set(topics)

    def on_connect(client, userdata, flags, rc):
        if rc == mqtt.MQTT_ERR_SUCCESS:
            log.info("MQTT client connected to %s:%s over %s",
                     config.firehose_host,
                     firehose_port, config.firehose_transport)
        fut.set_result(rc)

    def cleanup_and_raise(client, rc):
        try:
            client.disconnect()
        except IOError:
            pass
        error_msg_tpl = ("MQTT failed connecting to %s:%s over %s,"
                         " reason=%s")
        raise IOError(error_msg_tpl % (
            config.firehose_host,
            firehose_port,
            config.firehose_transport,
            mqtt.error_string(rc)))

    client = mqtt.Client(transport=config.firehose_transport)
    client.on_connect = on_connect
    client.connect(config.firehose_host, port=firehose_port)

    with timeutils.StopWatch(duration=max_connect_wait) as watch:
        awaiting_connect = True
        while awaiting_connect:
            if watch.expired() and not fut.done():
                cleanup_and_raise(client, mqtt.MQTT_ERR_NO_CONN)
            if fut.done():
                rc = fut.result()
                if rc != mqtt.MQTT_ERR_SUCCESS:
                    cleanup_and_raise(client, rc)
                else:
                    for topic in topics:
                        rc, _mid = client.subscribe(topic)
                        if rc == mqtt.MQTT_ERR_SUCCESS:
                            log.info("MQTT client subscribed to"
                                     " topic '%s'", topic)
                        else:
                            break
                    if rc != mqtt.MQTT_ERR_SUCCESS:
                        cleanup_and_raise(client, rc)
                    else:
                        awaiting_connect = False
            else:
                client.loop(check_delay)

    return client


def import_func(import_str):
    mod_str, _sep, func_str = import_str.rpartition('.')
    mod = importutils.import_module(mod_str)
    try:
        return getattr(mod, func_str)
    except AttributeError:
        raise ImportError("Function '%s' could not be found" % func_str)


def chop(issue, max_issue_size=4000, max_fallback_size=200):
    small_issue = issue[0:max_issue_size]
    if len(small_issue) < len(issue):
        small_issue += "..."
    smaller_issue = issue[0:max_fallback_size]
    if len(smaller_issue) < len(issue):
        smaller_issue += "..."
    return (small_issue, smaller_issue)


def prettify_yaml(obj, explicit_end=True, explicit_start=True):
    formatted = yaml.safe_dump(obj,
                               line_break="\n",
                               indent=4,
                               explicit_start=explicit_start,
                               explicit_end=explicit_end,
                               default_flow_style=False)
    return formatted


def render_template(contents, params,
                    variable_start_string=None,
                    variable_end_string=None):
    env_kwargs = {
        'undefined': jinja2.StrictUndefined,
        'trim_blocks': True,
    }
    if variable_start_string:
        env_kwargs['variable_start_string'] = variable_start_string
    if variable_end_string:
        env_kwargs['variable_end_string'] = variable_end_string
    env = jinja2.Environment(**env_kwargs)
    tpl = env.from_string(contents)
    return tpl.render(**params)
