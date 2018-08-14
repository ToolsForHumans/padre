# -*- coding: utf-8 -*-

import abc
import logging
import pkg_resources
import random

import munch
from oslo_utils import reflection

from padre import channel as c
from padre import handler
from padre import matchers
from padre import trigger
from padre import utils

LOG = logging.getLogger(__name__)


def _form_url(hostname, port=None, ssl_on=False):
    if port is None:
        port = 80
    if port == 443:
        url = "https://%s" % hostname
    elif port == 80:
        url = "http://%s" % hostname
    else:
        if ssl_on:
            url = "https://%s:%s" % (hostname, port)
        else:
            url = "http://%s:%s" % (hostname, port)
    return url


class ShowSomeUrlHandler(handler.TriggeredHandler):
    def _run(self):
        what = self._get_what_host_port_url()
        if not what.enabled:
            message = ("I don't know what my %s"
                       " url is :slightly_frowning_face:" % what.name)
        else:
            url = _form_url(what.hostname, port=what.port,
                            ssl_on=what.get("ssl_on", False))
            message = "My %s url is %s" % (what.name, url)
        replier = self.message.reply_text
        replier(message, threaded=True, prefixed=False)

    @abc.abstractmethod
    def _get_what_host_port_url(self):
        pass


class AraUrlHandler(ShowSomeUrlHandler):
    """Tells you what the bot's ara url is."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('ara url', takes_args=False),
        ],
    }

    def _get_what_host_port_url(self):
        try:
            ara_enabled = self.config.ara_enabled
        except AttributeError:
            ara_enabled = False
        ara_hostname = self.config.get("ara_hostname")
        if not ara_hostname:
            ara_hostname = self.bot.hostname
        return munch.Munch({
            'name': 'ara',
            'enabled': ara_enabled,
            'port': self.config.get("ara_port"),
            'hostname': ara_hostname,
        })


class InfoUrlHandler(ShowSomeUrlHandler):
    """Tells you what the bot's information url is."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('info url', takes_args=False),
            trigger.Trigger('information url', takes_args=False),
        ],
    }

    def _get_what_host_port_url(self):
        try:
            status_port = self.config.status.port
        except AttributeError:
            status_port = None
        try:
            ssl_on = bool(self.config.status.ssl)
        except AttributeError:
            ssl_on = False
        return munch.Munch({
            'name': 'information',
            'enabled': bool(status_port),
            'port': status_port,
            'hostname': self.bot.hostname,
            'ssl_on': ssl_on,
        })


class Handler(handler.TriggeredHandler):
    """Shows various status-like information about this bot."""

    hello_messages = [
        "Hello there!",
        "Hi there!",
    ]
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('status', takes_args=False),
        ],
    }

    @staticmethod
    def _format_handler(handler):
        h_message_kind = reflection.get_class_name(handler.message)
        h_state = handler.state
        h_fields = [
            {
                'title': 'State',
                'value': h_state,
                'short': utils.is_short(h_state),
            },
            {
                'title': 'Message type',
                'value': h_message_kind,
                'short': utils.is_short(h_message_kind),
            },
        ]
        h_elapsed = None
        try:
            h_elapsed = handler.watch.elapsed()
        except RuntimeError:
            pass
        if h_elapsed is not None:
            h_elapsed = utils.format_seconds(h_elapsed)
            h_fields.append({
                'title': 'Elapsed',
                'value': h_elapsed,
                'short': utils.is_short(h_elapsed),
            })
        try:
            h_started_user = handler.message.body.user_name
        except AttributeError:
            pass
        else:
            if h_started_user:
                h_fields.append({
                    'title': 'Started by',
                    'value': h_started_user,
                    'short': utils.is_short(h_started_user),
                })
        try:
            h_quick_link = handler.message.body.quick_link
        except AttributeError:
            pass
        else:
            if h_quick_link:
                h_fields.append({
                    'title': 'Link',
                    'value': h_quick_link,
                    'short': utils.is_short(h_quick_link),
                })
        return {
            "pretext": u"• Handler `%s`" % reflection.get_class_name(handler),
            'mrkdwn_in': ['pretext'],
            'fields': h_fields,
        }

    def _run(self, **kwargs):
        me = pkg_resources.get_distribution('padre')
        bot_name = self.bot.name
        if not bot_name:
            bot_name = "???"
        started_at = self.bot.started_at
        now = self.date_wrangler.get_now()
        diff = now - started_at
        total_secs = int(max(0, diff.total_seconds()))
        attachments = [
            {
                'pretext': "I am known as `%s`." % bot_name,
                'mrkdwn_in': ['pretext'],
            },
            {
                'pretext': "I am %s version `%s`." % (me.key, me.version),
                'mrkdwn_in': ['pretext'],
            },
            {
                'pretext': "I have been alive for"
                           " %s." % utils.format_seconds(total_secs),
                'mrkdwn_in': [],
            },
        ]
        active_handlers = list(self.bot.active_handlers)
        if active_handlers:
            handlers_text = '`%s` handler' % len(active_handlers)
            if len(active_handlers) >= 2:
                handlers_text += "s"
            handlers_text += ":"
        else:
            handlers_text = 'no handlers.'
        attachments.append({
            'pretext': "I am running %s" % handlers_text,
            'mrkdwn_in': ['pretext'],
        })
        for h in active_handlers:
            attachments.append(self._format_handler(h))
        self.message.reply_attachments(
            attachments=attachments,
            log=LOG, link_names=False,
            as_user=True, text=random.choice(self.hello_messages),
            thread_ts=self.message.body.ts,
            channel=self.message.body.channel,
            unfurl_links=False)
