# -*- coding: utf-8 -*-

import logging

import github
from oslo_utils import units
import tabulate

import datetime
import dateparser
import time

from voluptuous import All
from voluptuous import Length
from voluptuous import Required
from voluptuous import Optional
from voluptuous import Schema

from padre import channel as c
from padre import handler
from padre import matchers
from padre import schema_utils as scu
from padre import trigger

LOG = logging.getLogger(__name__)


class TranscribeHandler(handler.TriggeredHandler):
    """Will create a transcript of the given time range"""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('transcribe', takes_args=True),
        ],
        'args': {
            'order': [
                'start',
                'stop',
            ],
            'help': {
                'start': 'time or link at which to start transcribing',
                'stop': 'time or link at which to stop transcribing',
            },
            'defaults': {
                'stop': 'now',
            },
            'schema': Schema({
                Required("start"): All(scu.string_types(), Length(min=1)),
                Optional("stop"): All(scu.string_types(), Length(min=1)),
            }),
        },
    }

    def _run(self, start, stop):
        slack_client = self.bot.clients.slack_client
        replier = self.message.reply_text
        replier("Slurping up messages from `%s`..." % (start),
            threaded=True, prefixed=False)
        start_dt = dateparser.parse(start)
        if start_dt is None:
            replier("ERR: I don't know how to parse that start date", threaded=True, prefixed=False)
            return
        if stop:
            replier("... to `%s`..." % (stop), threaded=True, prefixed=False)
            stop_dt = dateparser.parse(start)
            if stop_dt is None:
                replier("ERR: I don't know how to parse that stop date", threaded=True, prefixed=False)
                return
        else:
            stop_dt = datetime.now()
        replier("Parsed date range: `%s` to `%s`" % (start_dt.isoformat(), stop_dt.isoformat()),
            threaded=True, prefixed=False)

        start_ts = time.mktime(start_dt.timetuple())
        stop_ts = time.mktime(stop_dt.timetuple())
        result = slack_client.api_call("conversations.history", channel=self.message.body['channel'], oldest=start_ts, latest=stop_ts, types='public_channel,mpim')
        replier("Response: ```%s```" % (result), threaded=True, prefixed=False)
        print(result)
