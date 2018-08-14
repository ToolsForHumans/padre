import logging

import pkginfo
import six

from padre import channel as c
from padre import handler
from padre import matchers
from padre import trigger

LOG = logging.getLogger(__name__)


def _format_pkg(pkg, pkg_info_attrs):
    lines = []
    for attr in pkg_info_attrs:
        val = getattr(pkg, attr, None)
        if not val:
            continue
        nice_attr = attr
        if isinstance(val, (tuple, list)):
            val = "\n".join([str(v) for v in val])
            val = val.strip()
        if not isinstance(val, six.string_types):
            val = str(val)
        if val == 'UNKNOWN' or len(val) == 0:
            continue
        nice_attr = nice_attr.replace("_", " ")
        nice_attr = nice_attr[0].upper() + nice_attr[1:]
        if "\n" in val:
            lines.append("_%s_:" % nice_attr)
            lines.append("```")
            lines.append(val)
            lines.append("```")
        else:
            lines.append("_%s_: `%s`" % (nice_attr, val))
    return lines


class Handler(handler.TriggeredHandler):
    """Shows what this bot is."""

    what = 'padre'
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('what are you', takes_args=False),
            trigger.Trigger('what are you?', takes_args=False),
        ],
    }
    pkg_info_attrs = tuple([
        'author_email',
        'author',
        'classifiers',
        'description',
        'home_page',
        'license',
        'name',
        'platform',
        'summary',
        'version',
    ])

    def _run(self, **kwargs):
        replier = self.message.reply_text
        me = pkginfo.get_metadata(self.what)
        if not me:
            replier(
                "I am not really sure what I am.",
                threaded=True, prefixed=False)
        else:
            lines = _format_pkg(me, self.pkg_info_attrs)
            if lines:
                replier = self.message.reply_attachments
                attachment = {
                    'pretext': "I am the following:",
                    'text': "\n".join(lines),
                    'mrkdwn_in': ['text'],
                }
                replier(text=' ', log=LOG, attachments=[attachment],
                        link_names=True, as_user=True,
                        channel=self.message.body.channel,
                        thread_ts=self.message.body.ts)
            else:
                replier(
                    "I am not really sure what I am.",
                    threaded=True, prefixed=False)
