from __future__ import absolute_import

import datetime
import logging

import pytz

from padre import channel as c
from padre import handler
from padre import matchers
from padre import slack_utils as su
from padre import utils

LOG = logging.getLogger(__name__)
UNKNOWN_STATUS = 255
UNKNOWN_EVENT_REGION = 'openstack-phx-private'
ENV_ANY = "*"
STATUS_MAP = {
    0: 'OK',
    1: 'WARNING',
    2: 'CRITICAL',
    UNKNOWN_STATUS: 'UNKNOWN',
}
COLOR_MAP = {
    0: su.COLORS.green,
    1: su.COLORS.orange,
    2: su.COLORS.red,
    UNKNOWN_STATUS: su.COLORS.purple,
}


def _get_deep_attr(target, attr_name):
    if not attr_name:
        raise ValueError("Empty attributes not allowed")
    attr_name_pieces = attr_name.split(".")
    value = None
    value_found = False
    tmp_target = target
    while attr_name_pieces:
        tmp_attr_name = attr_name_pieces.pop(0)
        try:
            tmp_target = getattr(tmp_target, tmp_attr_name)
        except (TypeError, AttributeError, ValueError, IndexError):
            break
        else:
            if not attr_name_pieces:
                value = tmp_target
                value_found = True
    return (value_found, value)


class BroadcastEventHandler(handler.Handler):
    """Handler that turns sensu events into slack messages."""

    config_section = 'sensu'
    handles_what = {
        'message_matcher': matchers.match_sensu(),
        'channel_matcher': matchers.match_channel(c.BROADCAST),
    }
    requires_slack_sender = True
    required_configurations = ('event_channels',)

    @classmethod
    def handles(cls, message, channel, config):
        channel_matcher = cls.handles_what['channel_matcher']
        if not channel_matcher(channel):
            return None
        message_matcher = cls.handles_what['message_matcher']
        if not message_matcher(message, cls):
            return None
        if config.get('event_channels'):
            return handler.HandlerMatch()
        else:
            return None

    def _build_attachment(self, event, event_color, message_text):
        maybe_fields = []
        maybe_attrs = [
            ("action", ""),
            ("check.name", "Event name"),
            ("check.type", "Event type"),
            ("silenced", ""),
        ]
        for attr_name, pretty_name in maybe_attrs:
            value_found, value = _get_deep_attr(event, attr_name)
            if value_found:
                if not pretty_name:
                    pretty_name = attr_name.title()
                value = str(value)
                maybe_fields.append({
                    "title": pretty_name,
                    "value": value,
                    "short": utils.is_short(value),
                })
        attachment = {
            "footer": "Sensu",
            "footer_icon": ("https://raw.githubusercontent.com/sensu/"
                            "sensu-logo/master/"
                            "sensu1_flat%20white%20bg_png.png"),
            "color": event_color,
            "text": message_text,
            'mrkdwn_in': ["text"],
        }
        if maybe_fields:
            attachment['fields'] = maybe_fields
        return attachment

    def _build_in_alarm_for(self, event):
        event_action = event.get("action", "resolve")
        if event_action == 'resolve':
            in_alarm_for = ''
        else:
            try:
                # Discussion with the sensu folks determined that these
                # timestamps are all in zulu
                # time (aka +0 UTC); ie just UTC (so force it from a unix
                # timestamp into a timestamp with that timezone).
                last_ok = datetime.datetime.fromtimestamp(
                    int(event.last_ok), pytz.UTC)
            except (AttributeError, TypeError, ValueError):
                in_alarm_for = ''
            else:
                now = self.date_wrangler.get_now()
                bad_for = now - last_ok
                in_alarm_for_pieces = []
                if bad_for.days > 0:
                    in_alarm_for_pieces.append(
                        "*" + str(bad_for.days) + " days*")
                bad_for_seconds = bad_for.seconds
                bad_for_hours = bad_for_seconds / (60 * 60)
                if bad_for_hours > 0:
                    in_alarm_for_pieces.append(
                        "*" + str(bad_for_hours) + " hours*")
                bad_for_seconds = bad_for_seconds - (bad_for_hours * (60 * 60))
                bad_for_minutes = bad_for_seconds / 60
                if bad_for_minutes > 0:
                    in_alarm_for_pieces.append(
                        "*" + str(bad_for_minutes) + " minutes*")
                bad_for_seconds = bad_for_seconds - (bad_for_minutes * 60)
                if bad_for_seconds > 0:
                    in_alarm_for_pieces.append(
                        "*" + str(bad_for_seconds) + " seconds*")
                if in_alarm_for_pieces:
                    in_alarm_for = "(in alarm for "
                    in_alarm_for += " and ".join(in_alarm_for_pieces)
                    in_alarm_for += ")"
                else:
                    in_alarm_for = ''
        return in_alarm_for

    def _build_event_output(self, event):
        try:
            event_output = event.check.notification
            event_output = event_output.strip()
        except AttributeError:
            event_output = ''
        if not event_output:
            try:
                event_output = event.check.output
                event_output = event_output.strip()
            except AttributeError:
                event_output = ''
        return event_output

    def _build_incident(self, event):
        try:
            incident = event.client.name + "/" + event.check.name
        except AttributeError:
            incident = ''
        return incident

    def _process_event(self, event, event_channels):
        event_output = self._build_event_output(event)
        in_alarm_for = self._build_in_alarm_for(event)
        incident = self._build_incident(event)
        try:
            event_status = event.check.get('status', UNKNOWN_STATUS)
        except AttributeError:
            event_status = UNKNOWN_STATUS
        status_prefix = STATUS_MAP.get(event_status)
        if status_prefix is None:
            status_prefix = STATUS_MAP[UNKNOWN_STATUS]
        event_color = COLOR_MAP.get(event_status)
        if event_color is None:
            event_color = COLOR_MAP[UNKNOWN_STATUS]
        message_text = "*%s*: " % status_prefix
        if incident:
            message_text += incident
        if in_alarm_for:
            message_text += " " + in_alarm_for
        if event_output:
            message_text += "\n"
            message_text += "*Description*: %s" % event_output
        attachment = self._build_attachment(event, event_color, message_text)
        for channel in event_channels:
            self.bot.slack_sender.post_send(
                channel=channel,
                text=' ', link_names=True,
                unfurl_links=True,
                as_user=True,
                attachments=[attachment], log=LOG)

    def _run(self, **kwargs):
        event = self.message.body
        self._process_event(event, self.config.event_channels)
