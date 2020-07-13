# -*- coding: utf-8 -*-

import itertools
import logging
import pkg_resources
import random
import re
import socket
import threading
import traceback

from miniboa import mbasync as async_boa
from miniboa import telnet
from miniboa import xterm

import munch
import six

from padre import channel as c
from padre import exceptions as excp
from padre import message
from padre import progress_bar as pb
from padre import slack_utils as su

LOG = logging.getLogger(__name__)

# See: miniboa/xterm.py
GRAY = '^K'
BLUE = '^b'
BRIGHT_BLUE = '^B'
GREEN = '^g'
BRIGHT_GREEN = '^G'
RED = '^r'
BRIGHT_RED = '^R'
MAGENTA = '^m'
BRIGHT_MAGENTA = '^M'
CYAN = '^c'
BRIGHT_CYAN = '^C'
YELLOW = '^y'
BRIGHT_YELLOW = '^Y'
COLORS = tuple([
    BLUE, BRIGHT_BLUE,
    GREEN, BRIGHT_GREEN,
    RED, BRIGHT_RED,
    MAGENTA, BRIGHT_MAGENTA,
    CYAN, BRIGHT_CYAN,
    YELLOW, BRIGHT_YELLOW,
    GRAY,
])
UNDERLINE = '^U'
BOLD = '^!'
RESET = '^~'
UNICODE_REPLACEMENTS = tuple([
    # Because we use this a lot for lists and such and if we
    # use the ascii encoding (that replaces it) it will turn into '?'
    # due to encoding of that not being translatable... (which
    # we can just avoid).
    (u'•', '*'),
])
UNICODE_TARGET_ENCODING = 'ascii'


def _rainbow_colorize(text):
    buf = six.StringIO()
    for ch in text:
        buf.write(random.choice(COLORS))
        buf.write(ch)
    if text:
        buf.write(RESET)
    return buf.getvalue()


def _block_text(text):
    lines = []
    tmp_text = xterm.strip_caret_codes(text)
    lines.append("-" * len(tmp_text))
    lines.append(text)
    lines.append("-" * len(tmp_text))
    return "\n".join(lines)


def _escape_caret(text):
    # Avoids miniboa getting confused by user text that just may
    # have the same escape codes.
    return text.replace("^", "^^")


def _cook_traceback(tb_text):
    tb_text = _escape_caret(tb_text)
    tb_text_lines = tb_text.splitlines()
    tb_text_lines[0] = RED + BOLD + tb_text_lines[0] + RESET
    if len(tb_text_lines) > 1:
        tb_text_lines[1] = YELLOW + tb_text_lines[1]
        tb_text_lines[-1] = tb_text_lines[-1] + RESET
    tb_text = "\n".join(tb_text_lines)
    if not tb_text.endswith("\n"):
        tb_text += "\n"
    return tb_text


def _cook_slack_text(text, replace_mrkdwn=True):

    def replace_bolding(m):
        return BOLD + m.group(1) + RESET

    text_pieces = su.parse(text)
    text = su.drop_links(text_pieces)
    text = _escape_caret(text)

    if replace_mrkdwn:
        text = re.sub(r"[*](.*?)[*]", replace_bolding, text,
                      flags=re.MULTILINE)

    if isinstance(text, six.text_type):
        for u_ch, b_ch in UNICODE_REPLACEMENTS:
            text = text.replace(u_ch, b_ch)
        text = text.encode(
            UNICODE_TARGET_ENCODING, errors='replace')

    return text


def _cook_message_ts(m):
    buf = six.StringIO()
    buf.write(GREEN + str(m.body.ts) + RESET)
    if m.body.thread_ts is not None:
        buf.write(" (directed at thread ")
        buf.write(CYAN + str(m.body.thread_ts) + RESET)
        buf.write(")")
    return buf.getvalue()


class TelnetClient(telnet.TelnetClient):
    def __init__(self, sock, addr_tup):
        super(TelnetClient, self).__init__(sock, addr_tup)
        self.futs = []
        self.authed = False


class ManualTelnetProgressBar(pb.ManualProgressBar):
    def __init__(self, replier):
        self._replier = replier

    def update(self, done_text):
        self._replier(done_text)


class AutoTelnetProgressBar(pb.AutoProgressBar):
    def __init__(self, replier, max_am, update_period=1):
        super(AutoTelnetProgressBar, self).__init__(
            max_am, update_period=update_period)
        self._replier = replier

    def _trigger_change(self, percent_done):
        done_text = "%0.2f%% completed..." % percent_done
        self._replier(done_text)


class TelnetMessage(message.Message):
    def __init__(self, raw_kind, headers, body):
        super(TelnetMessage, self).__init__(raw_kind, headers, body)
        self._buffer = six.StringIO()
        self._buffer_lock = threading.Lock()

    @property
    def needs_drain(self):
        with self._buffer_lock:
            curr_pos = self._buffer.tell()
            if curr_pos == 0:
                return False
            return True

    def rewrite(self, text_aliases=None):
        if not text_aliases:
            return self
        try:
            new_text = text_aliases[self.body.text]
        except KeyError:
            return self
        else:
            new_me = self.copy()
            new_me.body.text = new_text
            new_me.body.text_no_links = new_text
            return new_me

    def drain_buffer(self):
        with self._buffer_lock:
            buf = self._buffer.getvalue()
            self._buffer.seek(0)
            self._buffer.truncate()
            return buf

    def make_manual_progress_bar(self):
        return ManualTelnetProgressBar(self.reply_text)

    def make_progress_bar(self, max_am, update_period=1):
        return AutoTelnetProgressBar(self.reply_text, max_am,
                                     update_period=update_period)

    def reply_attachments(self, attachments, **kwargs):
        buf = six.StringIO()
        text = kwargs.get("text")
        if text:
            buf.write(_cook_slack_text(text, replace_mrkdwn=False))
            if not text.endswith("\n"):
                buf.write("\n")
        for attachment in attachments:
            tmp_mrkdwn_in = set(attachment.get('mrkdwn_in', []))
            if 'fallback' in attachment:
                buf.write(_cook_slack_text(attachment['fallback'],
                                           replace_mrkdwn=False))
                buf.write("\n")
                continue
            if 'pretext' in attachment:
                buf.write(
                    _cook_slack_text(
                        attachment['pretext'],
                        replace_mrkdwn=('pretext' in tmp_mrkdwn_in)))
                buf.write("\n")
            if 'text' in attachment:
                for line in attachment['text'].splitlines():
                    buf.write("  ")
                    buf.write(
                        _cook_slack_text(
                            line, replace_mrkdwn=('text' in tmp_mrkdwn_in)))
                    buf.write("\n")
        out_buf = buf.getvalue()
        if out_buf:
            with self._buffer_lock:
                self._buffer.write(out_buf)

    def reply_text(self, text, **kwargs):
        buf = six.StringIO()
        buf.write(_cook_slack_text(text))
        buf.write("\n")
        with self._buffer_lock:
            self._buffer.write(buf.getvalue())


class Watcher(threading.Thread):
    WAIT_TIMEOUT = 0.1
    IDLE_TIMEOUT = 10 * 60
    MAX_CONNECTIONS = 5
    PORT = 6666

    pw_prompt = "Password: "
    prompt_tpl = "%(name)s Telnet Server> "
    what = 'padre'
    welcome_tpl = ("You have connected to the " + BRIGHT_BLUE +
                   '%(name)s' + RESET + " " + BRIGHT_YELLOW + "v%(version)s" +
                   RESET + " telnet server.")

    def __init__(self, bot, conf, address='localhost'):
        super(Watcher, self).__init__()
        self.bot = bot
        self.dead = threading.Event()
        self.address = address
        self.port = int(conf.get("port", self.PORT))
        self.password = conf.get("password")
        self.max_connections = int(max(1, conf.get("max_connections",
                                                   self.MAX_CONNECTIONS)))
        self.idle_timeout = float(conf.get("idle_timeout", self.IDLE_TIMEOUT))
        self._ts_counter = itertools.count(0)
        self._server = None

    def client_count(self):
        if self._server is None:
            return 0
        return self._server.client_count()

    @classmethod
    def _make_prompt(cls):
        return cls.prompt_tpl % {'name': _rainbow_colorize(cls.what.title())}

    @classmethod
    def _make_welcome(cls):
        me = pkg_resources.get_distribution(cls.what)
        welcome = cls.welcome_tpl % {'name': cls.what, 'version': me.version}
        return welcome

    def _on_connect(self, client):
        client_name = client.addrport()
        LOG.debug("Session to %s opened.", client_name)
        buf = six.StringIO()
        if self.password:
            buf.write(self.pw_prompt)
            authed = False
        else:
            buf.write(self._make_welcome() + "\n")
            buf.write(self._make_prompt())
            authed = True
        client.send_cc(buf.getvalue())
        client.authed = authed
        if self.password:
            client.password_mode_on()

    def _on_disconnect(self, client):
        client_name = client.addrport()
        LOG.debug("Session to %s closing.", client_name)
        ok_closed = False
        try:
            try:
                client.sock.shutdown(socket.SHUT_RDWR)
            except socket.error:
                pass
            while client.futs:
                fut = client.futs.pop(0)
                fut.cancel()
        finally:
            try:
                client.sock.close()
                ok_closed = True
            except socket.error:
                LOG.warning("Failed closing socket to %s.", client_name,
                            exc_info=True)
        if ok_closed:
            LOG.debug("Session to %s closed.", client_name)

    def _kick_idle(self):
        for client in list(six.itervalues(self._server.clients)):
            if not client.active:
                continue
            if client.idle() >= self.idle_timeout:
                LOG.debug("Kicking idle session %s.", client.addrport())
                client.deactivate()

    def _process_clients_futs(self, clients_needing_prompt):
        for client in list(six.itervalues(self._server.clients)):
            if not client.active:
                continue
            client_name = client.addrport()
            if not client.futs or not client.authed:
                continue
            not_done = []
            done = []
            buf = six.StringIO()
            for fut in client.futs:
                if not fut.done():
                    not_done.append(fut)
                else:
                    done.append(fut)
                if fut.message.needs_drain:
                    title_text = "Thread %s" % _cook_message_ts(fut.message)
                    title_text += " produced some output"
                    buf.write(_block_text(title_text))
                    buf.write("\n")
                    tmp_out = fut.message.drain_buffer()
                    buf.write(tmp_out)
                    if not tmp_out.endswith("\n"):
                        buf.write("\n")
            for fut in done:
                title_text = "Thread %s" % _cook_message_ts(fut.message)
                try:
                    res = fut.result()
                except excp.Dying:
                    title_text += " committed suicide"
                    buf.write(_block_text(title_text))
                    buf.write("\n")
                    buf.write(BRIGHT_RED + "Program dying" + RESET + "!")
                    buf.write("\n")
                except Exception as e:
                    if isinstance(e, excp.NoHandlerFound) and e.suggestion:
                        title_text += " produced a suggestion"
                        buf.write(_block_text(title_text))
                        buf.write("\n")
                        buf.write("Perhaps you meant ")
                        buf.write(UNDERLINE + BOLD)
                        buf.write(_escape_caret(e.suggestion))
                        buf.write(RESET)
                        buf.write("?\n")
                    else:
                        title_text += " produced a failure"
                        buf.write(_block_text(title_text))
                        buf.write("\n")
                        tmp_buf = six.StringIO()
                        traceback.print_exc(file=tmp_buf)
                        buf.write(_cook_traceback(tmp_buf.getvalue()))
                else:
                    title_text += " produced some result"
                    buf.write(_block_text(title_text))
                    buf.write("\n")
                    buf.write(_escape_caret(str(res)))
                    buf.write("\n")
            buf = buf.getvalue()
            if buf:
                if client_name not in clients_needing_prompt:
                    client.send("\n")
                client.send_cc(buf)
                clients_needing_prompt.add(client_name)
            client.futs = not_done

    def _process_clients_input(self, clients_needing_prompt):
        for client in list(six.itervalues(self._server.clients)):
            if not client.active or not client.cmd_ready:
                continue
            client_name = client.addrport()
            client_cmd = client.get_command()
            client_cmd = client_cmd.strip()
            if not client.authed:
                if client_cmd != self.password:
                    client.deactivate()
                else:
                    client.authed = True
                    client.password_mode_off()
                    buf = six.StringIO()
                    buf.write("\n")
                    buf.write(self._make_welcome() + "\n")
                    buf.write(self._make_prompt())
                    client.send_cc(buf.getvalue())
                continue
            if client_cmd.lower() in ('quit', 'logout', 'exit', 'bye'):
                client.deactivate()
            elif client_cmd.lower() == 'ping':
                buf = six.StringIO()
                buf.write(_rainbow_colorize("pong"))
                buf.write("\n")
                client.send_cc(buf.getvalue())
                clients_needing_prompt.add(client_name)
            else:
                clients_needing_prompt.add(client_name)
                if client_cmd:
                    m_headers = {
                        message.VALIDATED_HEADER: True,
                        message.TO_ME_HEADER: True,
                        message.CHECK_AUTH_HEADER: False,
                    }
                    ts = str(six.next(self._ts_counter))
                    thread_ts = None
                    t_m = re.match(r"^@(\d+)\s+(.*)$", client_cmd)
                    if t_m:
                        thread_ts = t_m.group(1)
                        client_cmd = t_m.group(2)
                    # NOTE: Made to mostly look like a slack message body so
                    # that existing handlers don't care about
                    # the differences.
                    m_body = munch.Munch({
                        'text': client_cmd,
                        'ts': ts,
                        'thread_ts': thread_ts,
                        'text_no_links': client_cmd,
                        'user_id': client_name,
                        'user_name': client_name,
                        'channel': client_name,
                        'channel_id': client_name,
                        'quick_link': '',
                        'directed': True,
                    })
                    m_kind = "telnet/message"
                    m = TelnetMessage(m_kind, m_headers, m_body)
                    if thread_ts is None:
                        fut = self.bot.submit_message(m, c.TARGETED)
                    else:
                        fut = self.bot.submit_message(m, c.FOLLOWUP)
                    client.futs.append(fut)
                    buf = six.StringIO()
                    buf.write("Submitted thread %s" % _cook_message_ts(m))
                    buf.write("\n")
                    client.send_cc(buf.getvalue())

    def _process_clients_prompts(self, clients_needing_prompt):
        for client in list(six.itervalues(self._server.clients)):
            if not client.active:
                continue
            client_name = client.addrport()
            if client_name in clients_needing_prompt:
                client.send_cc(self._make_prompt())

    @staticmethod
    def insert_periodics(bot, scheduler):
        pass

    def setup(self):
        self._server = async_boa.TelnetServer(
            port=self.port, address=self.address,
            timeout=self.WAIT_TIMEOUT, on_connect=self._on_connect,
            on_disconnect=self._on_disconnect,
            max_connections=self.max_connections,
            client_class=TelnetClient)
        return ":".join(
            str(p) for p in self._server.server_socket.getsockname())

    def run(self):
        server = self._server
        try:
            while not self.dead.is_set():
                server.poll()
                self._kick_idle()
                cnp = set()
                self._process_clients_input(cnp)
                self._process_clients_futs(cnp)
                self._process_clients_prompts(cnp)
        finally:
            server.stop()
