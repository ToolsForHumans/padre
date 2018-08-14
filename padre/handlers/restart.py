# -*- coding: utf-8 -*-

import random

from padre import authorizers as auth
from padre import channel as c
from padre import handler
from padre import matchers
from padre import trigger


class Handler(handler.TriggeredHandler):
    """Causes the bot to restart itself."""

    ack_prefix = 'Restart acknowledged.'
    ack_messages = [
        "Be back in a bit!",
    ]
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('restart', takes_args=False),
        ],
        'authorizer': auth.user_in_ldap_groups('admins_cloud'),
    }

    def _run(self, **kwargs):
        ack_msg = self.ack_prefix
        ack_msg += " "
        ack_msg += random.choice(self.ack_messages)
        replier = self.message.reply_text
        replier(ack_msg, threaded=True, prefixed=False)
        if not self.bot.dead.is_set():
            self.bot.dead.set(self.bot.dead.RESTART)
