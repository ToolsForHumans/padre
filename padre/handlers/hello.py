# -*- coding: utf-8 -*-

import random

from padre import channel as c
from padre import handler
from padre import matchers
from padre import trigger


class Handler(handler.TriggeredHandler):
    """Welcomes you to the future!"""

    hellos = [
        'Hallo',
        'Bonjour',
        'Guten tag',
        u'Shalóm',
        'Konnichiwa',
        u'Namastē',
        'Hola',
        u'Nǐ hǎo',
    ]
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('hello', takes_args=False),
            trigger.Trigger('hi', takes_args=False),
            trigger.Trigger('howdy', takes_args=False),
        ],
    }

    def _run(self):
        hi_there = random.choice(self.hellos)
        replier = self.message.reply_text
        replier(hi_there, threaded=True, prefixed=False)
