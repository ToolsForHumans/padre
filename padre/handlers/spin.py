from padre import channel as c
from padre import handler
from padre import matchers
from padre import trigger

from oslo_utils import timeutils


class SpinHandler(handler.TriggeredHandler):
    """Handler that never stops (for testing)."""

    update_frequency = 5.0
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('spin', takes_args=False),
            trigger.Trigger('spinner', takes_args=False),
        ],
    }

    def _run(self):
        replier = self.message.reply_text
        m = self.message.make_manual_progress_bar()
        with timeutils.StopWatch() as w:
            replier("Spinner initiated.", threaded=True, prefixed=False)
            while not self.dead.is_set():
                self.dead.wait(self.update_frequency)
                if self.dead.is_set():
                    break
                else:
                    m.update("%0.2f seconds" % w.elapsed())
            replier("Spinner stopped.", threaded=True, prefixed=False)
