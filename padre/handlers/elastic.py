# -*- coding: utf-8 -*-

from __future__ import absolute_import

import functools
import logging
import re

import elasticsearch_dsl as e_dsl
import github as ghe
from oslo_utils import units
import six

from voluptuous import All
from voluptuous import Length
from voluptuous import Required
from voluptuous import Schema

from padre import authorizers as auth
from padre import channel as c
from padre import handler
from padre import matchers
from padre import schema_utils as su
from padre import trigger
from padre import utils


LOG = logging.getLogger(__name__)


def _format_hit(h, indent=4):
    h = h.to_dict()
    indent_d = indent * 2
    buf = six.StringIO()
    for k in sorted(six.iterkeys(h)):
        if k.startswith("@") or k.startswith("_"):
            continue
        v = h[k]
        buf.write("%s%s =>" % (" " * indent, k))
        buf.write("\n")
        if isinstance(v, (list, tuple, set)):
            for sub_v in sorted(v):
                buf.write("%s- %s" % (" " * indent_d, sub_v))
                buf.write("\n")
            continue
        if not isinstance(v, (six.string_types)):
            v = str(v)
        v_lines = v.splitlines()
        for line in v_lines:
            buf.write("%s%s" % (" " * indent_d, line))
            buf.write("\n")
    return buf.getvalue()


class Handler(handler.TriggeredHandler):
    """Searches various elastic indexes for things in (log)message fields."""

    index_and_query = [
        ('dcr.compute_*-*', 'message:"%(thing)s"'),
        ('dcr.openstack_logstash-*', 'logmessage:"%(thing)s"'),
    ]

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('elastic search logs', takes_args=True),
        ],
        'authorizer': auth.message_from_channels(
            ['openstack', 'team-openstack-eng']),
        'args': {
            'order': ['thing'],
            'help': {
                'thing': 'thing to find logs for',
            },
            'schema': Schema({
                Required("thing"): All(su.string_types(), Length(min=1)),
            }),
        },
    }
    required_clients = (
        'github',
        'elastic',
    )

    @staticmethod
    def _chop(fh, max_am):
        left, contents = utils.read_backwards_up_to(fh, max_am)
        if left:
            tmp_contents = "%s more..." % left
            tmp_contents += " " + contents
            contents = tmp_contents
        return contents

    def _run(self, thing):
        github_client = self.bot.clients.github_client
        elastic_client = self.bot.clients.elastic_client
        replier = functools.partial(self.message.reply_text,
                                    threaded=True, prefixed=False)
        replier("Initiating scan for `%s`." % thing)
        to_send = {}
        for index, query_tpl in self.index_and_query:
            query = query_tpl % {'thing': thing}
            replier("Scanning index `%s` using query `%s`." % (index, query))
            s = (e_dsl.Search(using=elastic_client)
                 .query("query_string", query=query)
                 .sort("-@timestamp").index(index))
            s_buf = six.StringIO()
            for i, h in enumerate(s.scan()):
                h_header = "Hit %s" % (i + 1)
                h_header_delim = "-" * len(h_header)
                h_header += "\n"
                h_header += h_header_delim
                h_header += "\n"
                s_buf.write(h_header)
                s_buf.write(_format_hit(h))
                s_buf.write("\n")
            # Github has upper limit on postings to 1MB
            s_buf = self._chop(s_buf, units.Mi)
            if s_buf:
                # Because github...
                s_buf_name = re.sub(r"\.|\-|\*|_", "", index)
                s_buf_name = s_buf_name + ".txt"
                to_send[s_buf_name] = ghe.InputFileContent(s_buf)
        if not to_send:
            replier("No scan results found.")
        else:
            replier("Uploading %s scan results to gist." % len(to_send))
            me = github_client.get_user()
            gist = me.create_gist(True, to_send)
            replier("Gist url at: %s" % gist.html_url)
