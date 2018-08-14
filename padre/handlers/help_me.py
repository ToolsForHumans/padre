# -*- coding: utf-8 -*-

import requests

from padre import channel as c
from padre import handler
from padre import matchers
from padre import trigger


class Handler(handler.TriggeredHandler):
    """Helps you (the user) with some useful buzzwords."""

    buzz_url = "http://www.buzzwordipsum.com/buzzwords/"
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('help me', takes_args=False),
        ],
    }

    def _run(self):
        bullshit_response_from_buzzwordipsum = requests.get(
            self.buzz_url,
            params={"format": "text", "paragraphs": "1", "type": "sentences"})
        bullshit_response_from_buzzwordipsum.raise_for_status()
        replier = self.message.reply_text
        replier(
            bullshit_response_from_buzzwordipsum.text.strip("\n"),
            threaded=True, prefixed=False)
