import logging

from padre import channel as c
from padre import handler
from padre import matchers
from padre import trigger
from padre import utils

LOG = logging.getLogger(__name__)


class Handler(handler.TriggeredHandler):
    """Show's how many seconds the bot has been alive for."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('uptime', takes_args=False),
        ],
    }

    def _run(self, **kwargs):
        started_at = self.bot.started_at
        replier = self.message.reply_text
        if started_at is None:
            replier(
                "I am not alive, how are you sending this?",
                threaded=True, prefixed=False)
        else:
            now = self.date_wrangler.get_now()
            diff = now - started_at
            replier(
                "I have been alive"
                " for %s." % utils.format_seconds(diff.total_seconds()),
                threaded=True, prefixed=False)
