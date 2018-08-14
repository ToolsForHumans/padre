import logging

from voluptuous import All
from voluptuous import Length
from voluptuous import Required
from voluptuous import Schema

from padre import channel as c
from padre import handler
from padre import matchers
from padre import schema_utils as scu
from padre import trigger

LOG = logging.getLogger(__name__)


class Handler(handler.TriggeredHandler):
    """Emit some message to some set of slack channels."""

    required_clients = ('slack',)
    requires_slack_sender = True
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('emit message', takes_args=True),
        ],
        'args': {
            'order': ['channels', 'message'],
            'schema': Schema({
                Required("channels"): All(scu.string_types(), Length(min=1)),
                Required("message"): All(scu.string_types(), Length(min=1)),
            }),
            'help': {
                'channels': ('comma separated list of channels'
                             ' to broadcast to'),
                'message': 'what to broadcast',
            },
        },
    }

    def _run(self, channels, message):
        slack_sender = self.bot.slack_sender
        slack_server = self.bot.clients.slack_client.server
        ok_channels = []
        seen = set()
        for maybe_c in channels.split(","):
            maybe_c = maybe_c.strip()
            if maybe_c and maybe_c not in seen:
                tmp_c = slack_server.channels.find(maybe_c)
                if tmp_c is None:
                    raise RuntimeError("Could not find channel '%s'" % maybe_c)
                else:
                    if tmp_c.id not in seen:
                        seen.add(maybe_c)
                        seen.add(tmp_c.id)
                        ok_channels.append(tmp_c)
        for ch in ok_channels:
            slack_sender.rtm_send(message, channel=ch.id)
