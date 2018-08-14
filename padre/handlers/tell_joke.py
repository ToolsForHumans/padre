# -*- coding: utf-8 -*-

import requests

from padre import channel as c
from padre import handler
from padre import matchers
from padre import trigger

OUT_HEADERS = {"Accept": "application/json"}


class Handler(handler.TriggeredHandler):
    """Hands out random jokes."""

    joke_url = 'http://icanhazdadjoke.com'

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('tell me a joke', takes_args=False),
        ],
    }

    def _run(self):
        resp = requests.get(self.joke_url, headers=OUT_HEADERS)
        resp.raise_for_status()
        joke = resp.json().get("joke")
        if not joke:
            joke_text = "No joke found when calling `%s`." % self.joke_url
        else:
            joke_text = joke
        replier = self.message.reply_text
        replier(joke_text, threaded=True, prefixed=False)
