# -*- coding: utf-8 -*-

import functools
import socket

from voluptuous import All
from voluptuous import Length
from voluptuous import Required
from voluptuous import Schema

from padre import channel as c
from padre import handler
from padre import matchers
from padre import schema_utils as su
from padre import trigger


class Handler(handler.TriggeredHandler):
    """Finds a hostnames ip address."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('dns lookup', takes_args=True),
        ],
        'args': {
            'order': ['hostname'],
            'help': {
                'hostname': 'hostname to lookup',
            },
            'schema': Schema({
                Required("hostname"): All(su.string_types(), Length(min=1)),
            }),
        },
    }

    def _run(self, hostname):
        replier = functools.partial(self.message.reply_text,
                                    threaded=True, prefixed=False)
        hostname_ip = socket.gethostbyname(hostname)
        replier(
            "The ip address for `%s` is `%s`" % (hostname, hostname_ip))
