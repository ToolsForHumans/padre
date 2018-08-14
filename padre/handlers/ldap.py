# -*- coding: utf-8 -*-

import logging

import github
from oslo_utils import units
import tabulate
from voluptuous import All
from voluptuous import Length
from voluptuous import Required
from voluptuous import Schema

from padre import channel as c
from padre import handler
from padre import ldap_utils
from padre import matchers
from padre import schema_utils as scu
from padre import trigger

LOG = logging.getLogger(__name__)


def _chop(contents, max_am):
    if len(contents) <= max_am:
        return contents
    else:
        tmp_contents = contents[0:max_am]
        left = len(contents) - len(tmp_contents)
        tmp_contents += "%s more..." % left
        return tmp_contents


class DescribeUserHandler(handler.TriggeredHandler):
    """Lists the details of some ldap user."""

    required_clients = ("ldap",)
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('ldap describe user', takes_args=True),
        ],
        'args': {
            'order': [
                'user',
            ],
            'help': {
                'user': 'user to describe',
            },
            'schema': Schema({
                Required("user"): All(scu.string_types(), Length(min=1)),
            }),
        },
    }

    def _run(self, user):
        ldap_client = self.bot.clients.ldap_client
        tmp_user = ldap_client.describe_user(user)
        replier = self.message.reply_text
        if not tmp_user:
            replier("No user with name `%s` found." % (user),
                    threaded=True, prefixed=False)
        else:
            tbl_headers = []
            row = []
            for k in sorted(tmp_user.keys()):
                v = tmp_user.get(k)
                if v is not None:
                    h_k = k.replace("_", ' ')
                    h_k = h_k[0].upper() + h_k[1:]
                    tbl_headers.append(h_k)
                    row.append(v)
            rows = [row]
            lines = [
                "```",
                tabulate.tabulate(rows, headers=tbl_headers),
                "```",
            ]
            replier("\n".join(lines), threaded=True, prefixed=False)


class ListHandler(handler.TriggeredHandler):
    """Lists the members of a ldap group."""

    required_clients = ("ldap", "github")
    max_before_gist = 100
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('ldap list', takes_args=True),
        ],
        'args': {
            'order': [
                'group',
            ],
            'help': {
                'group': 'ldap group to list',
            },
            'schema': Schema({
                Required("group"): All(scu.string_types(), Length(min=1)),
            }),
        },
    }

    def _run(self, group):
        replier = self.message.reply_text
        ldap_client = self.bot.clients.ldap_client
        group_members = [
            ldap_utils.explode_member(member)
            for member in ldap_client.list_ldap_group(group)
        ]
        group_members = sorted(group_members,
                               key=lambda m: m.get("CN"))
        tbl_headers = ['CN', 'DC', 'OU']
        rows = []
        for member in group_members:
            row = []
            for k in tbl_headers:
                v = member.get(k)
                if isinstance(v, list):
                    v = ", ".join(v)
                row.append(v)
            rows.append(row)
        if len(group_members) <= self.max_before_gist:
            lines = [
                "```",
                tabulate.tabulate(rows, headers=tbl_headers),
                "```",
            ]
            replier("\n".join(lines), threaded=True, prefixed=False)
        else:
            github_client = self.bot.clients.github_client
            me = github_client.get_user()
            to_send = {}
            upload_what = [
                ('listing', tabulate.tabulate(rows, headers=tbl_headers)),
            ]
            for what_name, contents in upload_what:
                # Github has upper limit on postings to 1MB
                contents = _chop(contents, units.Mi)
                contents = contents.strip()
                name = what_name + ".txt"
                to_send[name] = github.InputFileContent(contents)
            if to_send:
                try:
                    gist = me.create_gist(True, to_send)
                except Exception:
                    LOG.warning("Failed uploading gist for listing"
                                " of '%s' ldap group", group)
                else:
                    lines = [
                        "Gist url at: %s" % gist.html_url,
                    ]
                    replier("\n".join(lines), threaded=True, prefixed=False)
