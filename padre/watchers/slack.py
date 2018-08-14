import logging
import threading

from apscheduler.triggers import cron
import munch
from oslo_utils import reflection
import requests

from padre import channel as c
from padre import finishers
from padre import message
from padre import progress_bar as pb
from padre import slack_utils as su
from padre import utils

LOG = logging.getLogger(__name__)


def _pick_channel_thread_ts(m):
    if not m.body.thread_ts:
        return c.TARGETED
    else:
        return c.FOLLOWUP


def _should_broadcast(m, was_split):
    if was_split or _pick_channel_thread_ts(m) == c.FOLLOWUP:
        return False
    return True


def _form_kind(message_type, message_subtype=''):
    m_kind = 'slack/%s' % message_type
    if message_subtype:
        m_kind = m_kind + "/" + message_subtype
    return m_kind


def _targets_from_text(raw_message):
    m_targets, _m_text_pieces = su.extract_targets(
        su.parse(raw_message.get("text", '')))
    return m_targets


def _break_apart_message(bot, raw_message,
                         m_body, m_to_me):
    m_bodies = []
    was_split = False
    if 'files' not in raw_message or not m_to_me:
        m_targets, m_text_pieces = su.extract_targets(
            su.parse(raw_message.get("text", '')))
        m_text = "".join(t.text for t in m_text_pieces)
        m_text_no_links = su.drop_links(m_text_pieces)
        tmp_m_body = m_body.copy()
        tmp_m_body.text = m_text.lstrip()
        tmp_m_body.text_no_links = m_text_no_links.lstrip()
        m_bodies.append(tmp_m_body)
    else:
        slack_client = bot.clients.slack_client
        for f in raw_message.get('files', []):
            # TODO: get some native api in the slack client library
            # so we can avoid doing this... just to get at a file that the
            # library should be able to fetch...
            resp = requests.get(
                f['url_private_download'],
                headers={
                    'Authorization': 'Bearer %s' % slack_client.server.token,
                }, timeout=bot.config.slack.get('timeout'))
            resp.raise_for_status()
            resp_text = resp.text.strip()
            for line in resp_text.splitlines():
                tmp_m_body = m_body.copy()
                tmp_m_body.text = line.strip()
                tmp_m_body.text_no_links = tmp_m_body.text
                m_bodies.append(tmp_m_body)
        was_split = True
    return m_bodies, was_split


class ManualSlackProgressBar(pb.ManualProgressBar):
    def __init__(self, slack_sender, channel, thread_ts=None):
        self.slack_sender = slack_sender
        self.channel = channel
        self.thread_ts = thread_ts
        self._prior_response = {}

    def reset(self):
        super(ManualSlackProgressBar, self).reset()
        self._prior_response.clear()

    def _trigger_new(self, text):
        resp = self.slack_sender.post_send(channel=self.channel,
                                           text=text, as_user=True,
                                           thread_ts=self.thread_ts)
        self._prior_response.update(resp)

    def _trigger_prior(self, text, ts):
        resp = self.slack_sender.update_post_send(self.channel, text=text,
                                                  as_user=True, ts=ts)
        self._prior_response.update(resp)

    def update(self, done_text):
        try:
            self._trigger_prior(done_text, self._prior_response['ts'])
        except KeyError:
            self._trigger_new(done_text)


class AutoSlackProgressBar(pb.AutoProgressBar):
    def __init__(self, slack_sender, channel,
                 max_am, thread_ts=None,
                 update_period=1):
        super(AutoSlackProgressBar, self).__init__(
            max_am, update_period=update_period)
        self.slack_sender = slack_sender
        self.channel = channel
        self.thread_ts = thread_ts
        self._prior_response = {}

    def reset(self):
        super(AutoSlackProgressBar, self).reset()
        self._prior_response.clear()

    def _trigger_new(self, text):
        resp = self.slack_sender.post_send(channel=self.channel,
                                           text=text, as_user=True,
                                           thread_ts=self.thread_ts)
        self._prior_response.update(resp)

    def _trigger_prior(self, text, ts):
        resp = self.slack_sender.update_post_send(self.channel, text=text,
                                                  as_user=True, ts=ts)
        self._prior_response.update(resp)

    def _trigger_change(self, percent_done):
        done_text = "%0.2f%% completed..." % percent_done
        try:
            self._trigger_prior(done_text, self._prior_response['ts'])
        except KeyError:
            self._trigger_new(done_text)


class SlackMessage(message.Message):
    MAX_ATTACHMENTS = su.MAX_ATTACHMENTS

    def __init__(self, raw_kind, headers, body, slack_sender):
        super(SlackMessage, self).__init__(raw_kind, headers, body)
        self._slack_sender = slack_sender

    def rewrite(self, text_aliases=None):
        if not text_aliases:
            return self
        message_raw_text = self.body.text
        message_text = self.body.text_no_links
        for tmp_message_text, may_have_links in [(message_text, True),
                                                 (message_raw_text, False)]:
            try:
                tmp_message_text = text_aliases[tmp_message_text]
            except KeyError:
                pass
            else:
                new_me = self.copy()
                if may_have_links:
                    tmp_message_text_pieces = su.parse(tmp_message_text)
                    new_me.body.text = tmp_message_text
                    new_me.body.text_no_links = su.drop_links(
                        tmp_message_text_pieces)
                    new_me.body.text_pieces = tmp_message_text_pieces
                else:
                    new_me.body.text = tmp_message_text
                    new_me.body.text_no_links = tmp_message_text
                    new_me.body.text_pieces = su.parse(tmp_message_text)
                return new_me
        return self

    def make_manual_progress_bar(self):
        return ManualSlackProgressBar(self._slack_sender,
                                      self.body.channel,
                                      thread_ts=self.body.ts)

    def make_progress_bar(self, max_am, update_period=1):
        return AutoSlackProgressBar(self._slack_sender, self.body.channel,
                                    max_am, thread_ts=self.body.ts,
                                    update_period=update_period)

    def reply_attachments(self, attachments,
                          channel=None, text=None, username=None, as_user=None,
                          parse=None, link_names=None,
                          unfurl_links=None, unfurl_media=None, icon_url=None,
                          icon_emoji=None, thread_ts=None, log=None,
                          simulate_typing=True):
        if channel is None:
            channel = self.body.channel
        it = utils.iter_chunks(attachments, self.MAX_ATTACHMENTS)
        sender = self._slack_sender
        for i, tmp_attachments in enumerate(it):
            if i >= 1:
                text = None
            sender.post_send(channel, text=text, username=username,
                             as_user=as_user, attachments=tmp_attachments,
                             parse=parse, link_names=link_names,
                             unfurl_links=unfurl_links,
                             unfurl_media=unfurl_media,
                             icon_url=icon_url, icon_emoji=icon_emoji,
                             thread_ts=thread_ts, log=log,
                             simulate_typing=simulate_typing)

    def reply_text(self, text, prefixed=True,
                   threaded=False, thread_ts=None, log=None,
                   simulate_typing=True):
        message_channel = self.body.channel
        message_channel_kind = self.body.channel_kind
        message_user_id = self.body.user_id
        message_ts = self.body.ts
        if (message_channel_kind == su.ChannelKind.PUBLIC and
                prefixed and message_user_id):
            text = "%s: %s" % (su.make_mention(message_user_id), text)
        if threaded:
            if thread_ts:
                ts = thread_ts
            else:
                ts = message_ts
        else:
            ts = None
        sender = self._slack_sender
        return sender.rtm_send(text, message_channel,
                               thread=ts, log=log,
                               simulate_typing=simulate_typing)

    def to_dict(self):
        data = super(SlackMessage, self).to_dict()
        try:
            tmp_pieces = data['body']['text_pieces']
        except KeyError:
            pass
        else:
            n_tmp_pieces = []
            for p in tmp_pieces:
                n_tmp_pieces.append(str(p))
            data['body']['text_pieces'] = n_tmp_pieces
        try:
            data['body']['channel_kind'] = data['body']['channel_kind'].name
        except KeyError:
            pass
        return data


class SlackMessageProcessor(object):

    # Message type/subtype -> how to construct a message for it.
    processor_unknown = munch.Munch({
        'channel_selector_func': _pick_channel_thread_ts,
        'fail_handler_cls': finishers.log_on_fail,
        'broadcast_when_func': _should_broadcast,
        'kind_func': _form_kind,
        'target_extractor_func': lambda raw_message: set(),
        'delegate_up_func': lambda m_to_me: False,
    })
    processor_for_types = {
        'message': munch.Munch({
            'channel_selector_func': _pick_channel_thread_ts,
            'fail_handler_cls': finishers.notify_slack_on_fail,
            'broadcast_when_func': _should_broadcast,
            'target_extractor_func': _targets_from_text,
            'kind_func': _form_kind,
            'splitter_func': _break_apart_message,
            'delegate_up_func': lambda m_to_me: False,
        }),
    }

    def __init__(self, bot):
        self.bot = bot

    def _form_body(self, raw_message, message_type, user=None):
        slack_client = self.bot.clients.slack_client
        m_channel_id = raw_message.get("channel")
        m_channel_kind = su.ChannelKind.convert(m_channel_id)
        m_channel_name = None
        if m_channel_id:
            channel = slack_client.server.channels.find(m_channel_id)
            if channel:
                m_channel_name = channel.name
        if user:
            m_user_name = user.name
            m_user_tz = user.tz
            m_user_id = user.id
        else:
            m_user_name = None
            m_user_tz = None
            m_user_id = None
        m_body = munch.Munch({
            'ts': raw_message.get("ts"),
            'thread_ts': raw_message.get("thread_ts"),
            'channel': m_channel_id,
            'channel_name': m_channel_name,
            'channel_kind': m_channel_kind,
            'user_id': m_user_id,
            'user_name': m_user_name,
            'user_tz': m_user_tz,
            'directed': m_channel_kind == su.ChannelKind.DIRECTED,
        })
        return m_body

    def _submit_messages(self, messages):
        try:
            include_tracebacks = self.bot.config.include_tracebacks
        except AttributeError:
            include_tracebacks = False

        def _submit(m_entry):
            m, m_channel, m_broadcast, m_fail_cls = m_entry
            fut = self.bot.submit_message(m, m_channel)
            if m_fail_cls:
                fut.add_done_callback(
                    m_fail_cls(self.bot, m,
                               log=LOG, include_tracebacks=include_tracebacks))
            if m_broadcast:
                try:
                    b_fut = self.bot.submit_message(m, c.BROADCAST)
                except RuntimeError:
                    pass
                else:
                    b_fut.add_done_callback(
                        finishers.log_on_fail(
                            self.bot, m, log=LOG,
                            include_tracebacks=include_tracebacks))
            return fut

        def _submit_next_if_happy(fut):
            if not messages:
                return
            try:
                fut.result()
            except Exception:
                pass
            else:
                try:
                    next_fut = _submit(messages.pop(0))
                except RuntimeError:
                    pass
                else:
                    next_fut.add_done_callback(_submit_next_if_happy)

        if messages:
            fut = _submit(messages.pop(0))
            fut.add_done_callback(_submit_next_if_happy)

    def _generate_messages(self, raw_message, me,
                           message_type, processor, message_subtype='',
                           user=None):
        m_body = self._form_body(raw_message, message_type, user=user)
        m_targets = processor.target_extractor_func(raw_message)
        m_to_me = bool(set(m_targets) & me)
        if m_body.directed and not m_to_me:
            # These are always to me if directed... (even if not
            # prefixed to target myself...)
            m_targets.append(me)
            m_to_me = True
        m_body.targets = sorted(m_targets)
        try:
            splitter_func = processor.splitter_func
        except AttributeError:
            all_m_bodies = [m_body]
            was_split = False
        else:
            all_m_bodies, was_split = splitter_func(self.bot, raw_message,
                                                    m_body, m_to_me)
        all_m = []
        for m_body in all_m_bodies:
            m_kind = processor.kind_func(message_type,
                                         message_subtype=message_subtype)
            m_headers = {
                message.VALIDATED_HEADER: True,
                message.TO_ME_HEADER: m_to_me,
                message.CHECK_AUTH_HEADER: True,
            }
            m = SlackMessage(m_kind, m_headers,
                             m_body, self.bot.slack_sender)
            su.insert_quick_link(
                m, slack_base_url=self.bot.config.slack.get("base_url"))
            m_channel = processor.channel_selector_func(m)
            m_broadcast = processor.broadcast_when_func(m, was_split)
            all_m.append((m, m_channel,
                          m_broadcast, processor.fail_handler_cls))
        return all_m

    def _extract_processor(self, message_type, message_subtype=''):
        processor = None
        if message_subtype:
            k = message_type + "/" + message_subtype
            try:
                processor = self.processor_for_types[k]
            except KeyError:
                pass
        if processor is None:
            try:
                processor = self.processor_for_types[message_type]
            except KeyError:
                pass
        if processor is None:
            processor = self.processor_unknown
        return processor

    def process(self, me, raw_message):
        try:
            skip_types = self.bot.config.slack.skip_types
        except AttributeError:
            skip_types = []
        try:
            skip_users = self.bot.config.slack.skip_users
        except AttributeError:
            skip_users = []
        try:
            skip_bots = self.bot.config.slack.skip_bots
        except AttributeError:
            skip_bots = False
        message_type = raw_message.get("type", '')
        if not message_type or message_type in skip_types:
            return
        try:
            if message_type == 'user_change':
                m_user_id = raw_message['user']['id']
            else:
                m_user_id = raw_message['user']
        except KeyError:
            m_user_id = None
        if not m_user_id:
            return
        slack_client = self.bot.clients.slack_client
        user = slack_client.server.users.find(m_user_id)
        if user:
            m_user_name = user.name
        else:
            m_user_name = None
        m_bot_id = raw_message.get('bot_id')
        if (m_user_name in skip_users or
                m_user_id in skip_users or
                m_user_id in me or (m_bot_id and skip_bots)):
            return
        message_subtype = raw_message.get('subtype', '')
        processor = self._extract_processor(
            message_type, message_subtype=message_subtype)
        messages = self._generate_messages(
            raw_message, me, message_type, processor,
            message_subtype=message_subtype, user=user)
        self._submit_messages(messages)


class Watcher(threading.Thread):
    READ_WAIT_DELAY_SECS = 0.1

    def __init__(self, bot, on_connected=None, on_disconnected=None):
        super(Watcher, self).__init__()
        self.dead = threading.Event()
        self.bot = bot
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected
        self.daemon = True
        self.processor = SlackMessageProcessor(bot)

    @staticmethod
    def insert_periodics(bot, scheduler):
        try:
            ping_period = bot.config.slack.ping_period
            slack_client = bot.clients.slack_client
        except AttributeError:
            pass
        else:
            def ping_slack_rtm(slack_client):
                try:
                    rtm_connected = getattr(slack_client, 'rtm_connected')
                except AttributeError:
                    rtm_connected = False
                if rtm_connected and slack_client.server:
                    slack_client.server.ping()
                else:
                    LOG.warn("Slack RTM not connected, ping skipped")
            ping_slack_rtm.__doc__ = ('Periodically pings slack'
                                      ' via RTM/websocket'
                                      ' channel (to ensure they know we'
                                      ' are alive).')
            ping_slack_rtm_name = reflection.get_callable_name(ping_slack_rtm)
            ping_slack_rtm_description = ('Periodically pings slack'
                                          ' via RTM/websocket'
                                          ' channel (to ensure they know we'
                                          ' are alive).')
            scheduler.add_job(
                ping_slack_rtm,
                trigger=cron.CronTrigger.from_crontab(
                    ping_period, timezone=bot.config.tz),
                jobstore='memory',
                name="\n".join([ping_slack_rtm_name,
                                ping_slack_rtm_description]),
                id=utils.hash_pieces([ping_slack_rtm_name,
                                      ping_slack_rtm_description], max_len=8),
                args=(slack_client,),
                coalesce=True)

    def setup(self):
        slack_client = self.bot.clients.get("slack_client")
        if not slack_client:
            return
        # TODO: make this a client attribute, and not one we
        # have to tack on... upstream work...
        if not hasattr(slack_client, 'rtm_connected'):
            slack_client.rtm_connected = False
        if not hasattr(slack_client, 'rtm_lock'):
            slack_client.rtm_lock = threading.Lock()

    def run(self):
        slack_login_data = {}
        slack_client = self.bot.clients.slack_client

        def rtm_reconnector(initial_wait=1, max_wait=30):
            wait_secs = initial_wait
            while True:
                if slack_client.rtm_connected or self.dead.is_set():
                    break
                try:
                    # Improve this once the following merges:
                    #
                    # https://github.com/slackapi/python-slackclient/pull/216
                    with slack_client.rtm_lock:
                        slack_client.server.rtm_connect()
                    slack_login_data.clear()
                    slack_login_data.update(slack_client.server.login_data)
                    slack_client.rtm_connected = True
                except Exception:
                    LOG.exception("Failed rtm_reconnect, waiting %s"
                                  " seconds before next attempt",
                                  wait_secs)
                    self.dead.wait(wait_secs)
                    wait_secs = wait_secs * 2.0
                    wait_secs = min(wait_secs, max_wait)
                else:
                    if self.on_connected is not None:
                        self.on_connected(slack_login_data.copy())
            return slack_client.rtm_connected

        while not self.dead.is_set():
            if not slack_client.rtm_connected:
                if not rtm_reconnector():
                    continue
            try:
                with slack_client.rtm_lock:
                    raw_messages = slack_client.rtm_read()
            except Exception:
                # TODO: need better disconnection detection... like a
                # specific exception...
                slack_client.rtm_connected = False
                if self.on_disconnected is not None:
                    self.on_disconnected()
            else:
                for raw_message in raw_messages:
                    if self.dead.is_set():
                        break
                    me = set()
                    for k in ('name', 'id'):
                        try:
                            me.add(slack_login_data['self'][k])
                        except KeyError:
                            pass
                    try:
                        self.processor.process(me, raw_message)
                    except Exception:
                        LOG.exception("Failure processing slack"
                                      " message: %s", raw_message)
                self.dead.wait(self.READ_WAIT_DELAY_SECS)
