import logging
import pkg_resources

from padre import channel as c
from padre import handler
from padre import matchers
from padre import trigger

LOG = logging.getLogger(__name__)


class Handler(handler.TriggeredHandler):
    """Shows the version of the bot that is running."""
    what = 'padre'
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('version', takes_args=False),
        ],
    }

    def _run(self, **kwargs):
        me = pkg_resources.get_distribution(self.what)
        replier = self.message.reply_text
        if not me:
            replier(
                "I am not really sure what version I am.",
                threaded=True, prefixed=False)
        else:
            replier(
                "I am %s version `%s`." % (self.what, me.version),
                threaded=True, prefixed=False)
