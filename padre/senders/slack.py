import json
import logging
import math

import munch
from oslo_utils import timeutils
import six
from six.moves import range as compat_range
import tenacity

from slackclient import server

from tenacity.before import before_log
from tenacity.nap import sleep_using_event
from tenacity.retry import retry_if_exception
from tenacity.stop import stop_after_attempt
from tenacity.stop import stop_any
from tenacity.stop import stop_when_event_set
from tenacity.wait import wait_exponential

from padre import slack_utils as su

LOG = logging.getLogger(__name__)


def _filter_message(message):
    # Filter out all null/none because it appears slack doesn't
    # handle these correctly on there end and displays things like 'null'
    # where it should not...
    tmp_message = {}
    for k, v in six.iteritems(message):
        if v is not None:
            tmp_message[k] = v
    return tmp_message


def _convert_truthy(t):
    # TODO(harlowja): can we get rid of this function?
    if t is None:
        return None
    if t:
        return '1'
    else:
        return '0'


def _calculate_attachment_chars(text, attachments):
    c = 0
    if text:
        c += len(text)
    if attachments:
        for attachment in attachments:
            for k in ('pretext', 'text', 'fallback', 'title'):
                try:
                    c += len(attachment[k])
                except (KeyError, TypeError):
                    pass
            fields = attachment.get("fields")
            if fields:
                for f in fields:
                    for k in ('title', 'value'):
                        try:
                            c += len(f[k])
                        except (KeyError, TypeError):
                            pass
    return c


def _try_again_check(excp):
    if isinstance(excp, su.SlackError):
        return excp.is_retryable()
    else:
        return True


class _wait_exponential(wait_exponential):
    def __call__(self, previous_attempt_number, delay_since_first_attempt,
                 last_result=None):
        # See if: https://api.slack.com/docs/rate-limits happened
        # and use the built in retry-after if we can; otherwise switch
        # to backoff routine.
        delay = None
        if last_result is not None and last_result.failed:
            excp = last_result.exception()
            if (isinstance(excp, server.SlackConnectionError) and
                    excp.reply is not None and
                    excp.reply.status_code == 429):
                delay = excp.reply.headers.get('Retry-After')
        if delay is not None:
            try:
                delay = float(delay)
            except (TypeError, ValueError):
                delay = None
        if delay is not None:
            return max(0, min(delay, self.max))
        else:
            return super(_wait_exponential, self).__call__(
                previous_attempt_number, delay_since_first_attempt,
                last_result=last_result)


class Sender(object):
    DEFAULT_MAX_BACKOFF = 120
    DEFAULT_CHARS_PER_MINUTE = -1

    def __init__(self, bot):
        self.bot = bot
        self.active_typers = {}
        self.typing_chars_per_minute = self.DEFAULT_CHARS_PER_MINUTE

    def setup(self):
        self.active_typers.clear()
        try:
            chars_per_minute = int(self.bot.config.typing.chars_per_minute)
        except AttributeError:
            chars_per_minute = self.DEFAULT_CHARS_PER_MINUTE
        self.typing_chars_per_minute = chars_per_minute

    def _make_retry(self, log=None, max_attempts=None, max_backoff=None):
        if not log:
            log = LOG
        if max_backoff is None:
            try:
                max_backoff = float(self.bot.config.slack.max_backoff)
            except AttributeError:
                pass
        if max_backoff is None:
            max_backoff = self.DEFAULT_MAX_BACKOFF
        if max_attempts is None:
            try:
                max_attempts = int(self.bot.config.slack.max_attempts)
            except AttributeError:
                pass
        r_kwargs = {
            'sleep': sleep_using_event(self.bot.dead),
            'before': before_log(log, logging.DEBUG),
            'reraise': True,
            'wait': _wait_exponential(max=max_backoff),
            'retry': retry_if_exception(_try_again_check),
        }
        if max_attempts is not None and max_attempts > 0:
            r_kwargs['stop'] = stop_any(
                stop_after_attempt(max_attempts),
                stop_when_event_set(self.bot.dead))
        else:
            r_kwargs['stop'] = stop_when_event_set(self.bot.dead)
        r = tenacity.Retrying(**r_kwargs)
        return r

    def update_post_send(self, channel, ts, text=None,
                         as_user=None, attachments=None,
                         link_names=None, parse=None, log=None,
                         max_attempts=None, max_backoff=None,
                         simulate_typing=True):

        def sender(slack_client, message, timeout=None):
            result = slack_client.api_call(
                "chat.update", timeout=timeout, **message)
            was_ok = result.pop("ok", True)
            if not was_ok:
                raise su.SlackError(result["error"])
            result.pop("error", None)
            return result

        if attachments:
            out_attachments = json.dumps(attachments)
        else:
            out_attachments = None
        message = _filter_message({
            'as_user': _convert_truthy(as_user),
            'channel': channel,
            'text': text,
            'ts': ts,
            'link_names': link_names,
            'parse': parse,
            'attachments': out_attachments,
        })
        if simulate_typing:
            try:
                typed_chars = _calculate_attachment_chars(text, attachments)
                self._emit_typing(channel, typed_chars)
            except Exception:
                pass
        r = self._make_retry(log=log, max_attempts=max_attempts,
                             max_backoff=max_backoff)
        return r.call(sender, self.bot.clients.slack_client,
                      message, timeout=self.bot.config.slack.get("timeout"))

    def files_upload(self, channels, content, filename,
                     filetype=None, title=None, log=None, max_attempts=None,
                     max_backoff=None):

        def sender(slack_client, message, timeout=None):
            result = slack_client.api_call(
                "files.upload", timeout=timeout, **message)
            was_ok = result.pop("ok", True)
            if not was_ok:
                raise su.SlackError(result["error"])
            return munch.munchify(result['file'])

        message = _filter_message({
            'channels': channels,
            'file': content,
            'filename': filename,
            'filetype': filetype,
            'title': title,
        })
        r = self._make_retry(log=log, max_attempts=max_attempts,
                             max_backoff=max_backoff)
        return r.call(sender, self.bot.clients.slack_client,
                      message, timeout=self.bot.config.slack.get("timeout"))

    def im_open(self, user, return_im=True,
                log=None, max_attempts=None, max_backoff=None):

        def sender(slack_client, message, timeout=None):
            result = slack_client.api_call(
                "im.open", timeout=timeout, **message)
            was_ok = result.pop("ok", True)
            if not was_ok:
                raise su.SlackError(result["error"])
            return result['channel']['id']

        message = _filter_message({
            'user': user,
            'return_im': return_im,
        })
        r = self._make_retry(log=log, max_attempts=max_attempts,
                             max_backoff=max_backoff)
        return r.call(sender, self.bot.clients.slack_client,
                      message, timeout=self.bot.config.slack.get("timeout"))

    def post_send(self, channel, text=None, username=None, as_user=None,
                  parse=None, link_names=None, attachments=None,
                  unfurl_links=None, unfurl_media=None, icon_url=None,
                  icon_emoji=None, thread_ts=None, log=None,
                  max_attempts=None, max_backoff=None,
                  simulate_typing=True):

        def sender(slack_client, message, timeout=None):
            result = slack_client.api_call(
                "chat.postMessage", timeout=timeout, **message)
            was_ok = result.pop("ok", True)
            if not was_ok:
                raise su.SlackError(result["error"])
            result.pop("error", None)
            return result

        if attachments:
            out_attachments = json.dumps(attachments)
        else:
            out_attachments = None
        message = _filter_message({
            'as_user': _convert_truthy(as_user),
            'attachments': out_attachments,
            'channel': channel,
            'link_names': _convert_truthy(link_names),
            'text': text,
            'unfurl_links': _convert_truthy(unfurl_links),
            'unfurl_media': _convert_truthy(unfurl_media),
            'thread_ts': thread_ts,
            'parse': parse,
            'icon_emoji': icon_emoji,
            'icon_url': icon_url,
            'username': username,
        })
        if simulate_typing:
            try:
                typed_chars = _calculate_attachment_chars(text, attachments)
                self._emit_typing(channel, typed_chars)
            except Exception:
                pass
        r = self._make_retry(log=log, max_attempts=max_attempts,
                             max_backoff=max_backoff)
        return r.call(sender, self.bot.clients.slack_client,
                      message, timeout=self.bot.config.slack.get("timeout"))

    def _emit_typing(self, channel, typed_chars):
        chars_per_minute = self.typing_chars_per_minute
        slack_client = self.bot.clients.get("slack_client")
        if (chars_per_minute <= 0 or not slack_client or
                not slack_client.rtm_connected or typed_chars <= 0):
            return
        tmp_channel = slack_client.server.channels.find(channel)
        if not tmp_channel:
            channel_id = channel
        else:
            channel_id = tmp_channel.id
        chars_per_second = chars_per_minute / 60.0
        expected_sends = int(math.ceil(typed_chars / chars_per_second))
        LOG.debug("Emitting %s typing events (to match %s chars about"
                  " to be sent)", expected_sends, typed_chars)
        for _i in compat_range(0, expected_sends):
            if self.bot.dead.is_set():
                return
            # This avoids multiple senders from sending to the same
            # channel; which is not a recommended thing to do (this ensures
            # that only one will send, perhaps two if threads conflict
            # but it won't overload the same channel with typing
            # events).
            now = timeutils.now()
            last_sent = self.active_typers.get(channel_id, now - 2.0)
            if (now - last_sent) >= 1.0:
                self.active_typers[channel_id] = now
                with slack_client.rtm_lock:
                    slack_client.server.send_to_websocket({
                        'type': 'typing',
                        'channel': channel_id,
                    })
            self.bot.dead.wait(1.0)

    def rtm_send(self, text, channel, thread=None,
                 reply_broadcast=None, log=None, max_attempts=None,
                 max_backoff=None, simulate_typing=True):

        def sender(slack_client, text, channel,
                   thread=None, reply_broadcast=None):
            with slack_client.rtm_lock:
                return slack_client.rtm_send_message(
                    channel, text, thread=thread,
                    reply_broadcast=_convert_truthy(reply_broadcast))

        if simulate_typing:
            try:
                self._emit_typing(channel, len(text))
            except Exception:
                pass
        r = self._make_retry(log=log, max_attempts=max_attempts,
                             max_backoff=max_backoff)
        return r.call(sender, self.bot.clients.slack_client,
                      text, channel, thread=thread,
                      reply_broadcast=reply_broadcast)
