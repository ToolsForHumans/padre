# -*- coding: utf-8 -*-

import logging

from voluptuous import All
from voluptuous import Length
from voluptuous import Required
from voluptuous import Schema

from padre import channel as c
from padre import handler
from padre import matchers
from padre import schema_utils as su
from padre import trigger
from padre import utils

LOG = logging.getLogger(__name__)


class ClearHandler(handler.TriggeredHandler):
    """Remove all aliases (for the calling user)."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('alias clear', takes_args=False),
        ],
    }

    def _run(self):
        from_who = self.message.body.user_id
        if not from_who:
            return
        from_who = utils.to_bytes("user:%s" % from_who)
        with self.bot.locks.brain:
            try:
                user_info = self.bot.brain[from_who]
            except KeyError:
                user_info = {}
            if 'aliases' in user_info:
                num_aliases = len(user_info['aliases'])
                user_info['aliases'] = {}
                self.bot.brain[from_who] = user_info
                self.bot.brain.sync()
            else:
                num_aliases = 0
        replier = self.message.reply_text
        replier("Removed %s aliases." % num_aliases,
                threaded=True, prefixed=False)


class RemoveHandler(handler.TriggeredHandler):
    """Remove a alias to a long command (for the calling user)."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('alias remove', True),
        ],
        'schema': Schema({
            Required("short"): All(su.string_types(), Length(min=1)),
        }),
        'args': {
            'order': [
                'short',
            ],
            'help': {
                'short': 'alias of full command to remove',
            },
        },
    }

    def _run(self, short):
        from_who = self.message.body.user_id
        if not from_who:
            return
        from_who = utils.to_bytes("user:%s" % from_who)
        lines = []
        with self.bot.locks.brain:
            try:
                user_info = self.bot.brain[from_who]
            except KeyError:
                user_info = {}
            user_aliases = user_info.get('aliases', {})
            try:
                long = user_aliases.pop(short)
                self.bot.brain[from_who] = user_info
                self.bot.brain.sync()
                lines = [
                    ("Alias of `%s` to `%s` has"
                     " been removed.") % (short, long),
                ]
            except KeyError:
                lines = [
                    "No alias found for `%s`" % short,
                ]
        if lines:
            replier = self.message.reply_text
            replier("\n".join(lines), threaded=True, prefixed=False)


class AddHandler(handler.TriggeredHandler):
    """Alias a long command to a short(er) one (for the calling user)."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('alias add', True),
        ],
        'schema': Schema({
            Required("long"): All(su.string_types(), Length(min=1)),
            Required("short"): All(su.string_types(), Length(min=1)),
        }),
        'args': {
            'order': [
                'long',
                'short',
            ],
            'help': {
                'long': "full command",
                'short': 'shorter alias of full command',
            },
        },
    }

    def _run(self, long, short):
        from_who = self.message.body.user_id
        if not from_who:
            return
        from_who = utils.to_bytes("user:%s" % from_who)
        with self.bot.locks.brain:
            try:
                user_info = self.bot.brain[from_who]
            except KeyError:
                user_info = {}
            user_aliases = user_info.setdefault('aliases', {})
            user_aliases[short] = long
            self.bot.brain[from_who] = user_info
            self.bot.brain.sync()
            lines = [
                "Alias of `%s` to `%s` has been recorded." % (short, long),
            ]
        replier = self.message.reply_text
        replier("\n".join(lines), threaded=True, prefixed=False)
