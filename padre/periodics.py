# -*- coding: utf-8 -*-

import logging

from keystoneauth1 import exceptions as kaexcp
from novaclient import exceptions as nexcp
from oslo_utils import timeutils
from oslo_utils import units
import psutil
import tenacity

from padre import slack_utils as su
from padre import utils

LOG = logging.getLogger(__name__)


def _pretty_key(k):
    k = k.replace("_", " ")
    k = k.replace("-", " ")
    k = k.title()
    return k


def _make_retry(death_ev, max_attempts=3, max_backoff=30):
    r_stopper = tenacity.stop_when_event_set(death_ev)
    r_stopper = r_stopper | tenacity.stop_after_attempt(max_attempts)
    r_kwargs = {
        'sleep': tenacity.sleep_using_event(death_ev),
        'stop': r_stopper,
        'retry': tenacity.retry_if_exception_type(
            exception_types=(kaexcp.ConnectFailure, kaexcp.ConnectTimeout,
                             nexcp.ConnectionRefused, nexcp.RateLimit,
                             nexcp.OverLimit)),
        'wait': tenacity.wait_exponential(max=max_backoff),
    }
    return tenacity.Retrying(**r_kwargs)


class DangerZoneDetector(object):
    """Checks the health of environment the bot is running in.

    For now just checks available memory (but it can be expanded to
    do much more).
    """

    LOW_MEMORY = 1 * units.Gi
    REALLY_LOW_MEMORY = 512 * units.Mi

    #: This stops frequent broadcasts...
    EMIT_PERIOD = 60 * 30

    def __init__(self, bot):
        self.bot = bot
        self.last_sent = None

    @classmethod
    def is_enabled(cls, bot):
        return ('slack_client' in bot.clients and
                bot.slack_sender is not None and
                bot.config.get("admin_channel"))

    @classmethod
    def _build_attachments(cls, mem, memory_low=True):
        attachments = []
        if memory_low:
            fields = []
            for k in ('total', 'available', 'free',
                      'used', 'active', 'inactive'):
                try:
                    tmp_v = utils.format_bytes(getattr(mem, k))
                except AttributeError:
                    pass
                else:
                    fields.append({
                        'title': k.title(),
                        'value': tmp_v,
                        'short': utils.is_short(tmp_v),
                    })
            attachment = {
                'pretext': ':dangeeerrrzonnneee: Memory low!',
                'mrkdwn_in': ["pretext"],
                'fields': fields,
            }
            if mem.available <= cls.REALLY_LOW_MEMORY:
                attachment['color'] = su.COLORS.red
            else:
                attachment['color'] = su.COLORS.orange
            attachments.append(attachment)
        return attachments

    def _go_no_go(self):
        now = timeutils.now()
        if self.last_sent is None:
            return now, True
        if (now - self.last_sent) >= self.EMIT_PERIOD:
            return now, True
        return now, False

    def __call__(self):
        mem = psutil.virtual_memory()
        if mem.available <= self.LOW_MEMORY:
            now, do_it = self._go_no_go()
            if do_it:
                self.last_sent = now
                self.bot.slack_sender.post_send(
                    text="Good %s. I am running low on"
                         " resources." % self.bot.date_wrangler.get_when(),
                    channel=self.bot.config.admin_channel,
                    attachments=self._build_attachments(mem, memory_low=True),
                    as_user=True, simulate_typing=False,
                    log=LOG, link_names=True)
