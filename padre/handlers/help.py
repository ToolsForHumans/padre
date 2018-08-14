# -*- coding: utf-8 -*-

import logging

from padre import channel as c
from padre import handler
from padre import matchers
from padre import trigger

LOG = logging.getLogger(__name__)


class Handler(handler.TriggeredHandler):
    """Shows you what this bot can do."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('help', takes_args=True),
        ],
        'args': {
            'order': [
                'trigger',
            ],
            'converters': {},
            'help': {
                'trigger': "optional target trigger to get help on",
            },
        },
    }

    def _run(self, trigger=None):
        attachments = []
        if trigger:
            target_h = None
            for h in self.bot.handlers:
                if not h.has_help():
                    continue
                h_triggers = h.handles_what.get("triggers", [])
                h_match = False
                for h_trigger in h_triggers:
                    matched, _args = h_trigger.match(trigger)
                    if matched:
                        h_match = True
                        break
                if h_match:
                    target_h = h
                    break
            if target_h is None:
                replier = self.message.reply_text
                replier(
                    "Sorry I do not know of any"
                    " trigger `%s` (pick another?)" % trigger,
                    threaded=True, prefixed=False)
            else:
                title, how_to = target_h.get_help(self.bot)
                attachments.append({
                    'pretext': u"• %s" % title,
                    'text': "\n".join(how_to),
                    'mrkdwn_in': ['pretext', 'text'],
                })
        else:
            for h in self.bot.handlers:
                if not h.has_help():
                    continue
                title, how_to = h.get_help(self.bot)
                attachment = {
                    'pretext': u"• %s" % title,
                    'text': "\n".join(how_to),
                    'mrkdwn_in': ['pretext', 'text'],
                }
                attachments.append(attachment)
        if attachments:
            self.message.reply_attachments(
                attachments=attachments, log=LOG, link_names=True,
                as_user=True, thread_ts=self.message.body.ts,
                channel=self.message.body.channel,
                unfurl_links=False, simulate_typing=False)
