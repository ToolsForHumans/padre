# -*- coding: utf-8 -*-

import random

import requests

from padre import channel as c
from padre import handler
from padre import matchers
from padre import trigger


class Handler(handler.TriggeredHandler):
    """Say various trump phrases."""

    trump_url = 'https://api.whatdoestrumpthink.com/api/v1/quotes'
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('what would trump say', takes_args=False),
            trigger.Trigger('what would trump say?', takes_args=False),
            trigger.Trigger('trump say something', takes_args=False),
        ],
    }

    def _run(self):
        trump_messages = requests.get(self.trump_url)
        trump_messages.raise_for_status()
        message = random.choice(
            trump_messages.json()["messages"]["non_personalized"])
        replier = self.message.reply_text
        replier(message, threaded=True, prefixed=False)
