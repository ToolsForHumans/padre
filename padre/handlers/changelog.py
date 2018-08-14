# -*- coding: utf-8 -*-

import logging
import pkg_resources

from padre import channel as c
from padre import exceptions as excp
from padre import handler
from padre import matchers
from padre import trigger
from padre import updater_utils as uu

LOG = logging.getLogger(__name__)


class Handler(handler.TriggeredHandler):
    """Shows you what this bot changelog is (or another bot version)."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('changelog', takes_args=True),
        ],
        'args': {
            'order': [
                'version',
            ],
            'defaults': {
                'version': None,
            },
            'help': {
                'version': "optional version to get changelog of",
            },
        },
    }
    required_secrets = (
        'ci.artifactory.ro_account',
    )
    requires_slack_sender = True
    required_configurations = (
        'updater.project_url',
    )

    def _run(self, version=None):
        if not version:
            me = pkg_resources.get_distribution('padre')
            version = me.version
        project_url = self.bot.config.updater.project_url
        ro_account = self.bot.secrets.ci.artifactory.ro_account
        try:
            tmp_path = uu.check_fetch_version(
                version, ro_account, project_url)
        except excp.NotFound:
            replier = self.message.reply_text
            replier("No version `%s` found. Does it exist?" % version,
                    threaded=True, prefixed=False)
        else:
            changelog_lines = uu.extract_changelog(tmp_path.path)
            if not changelog_lines:
                pretext_lines = [
                    "No changelog found for `%s`." % version,
                ]
            else:
                pretext_lines = [
                    "Here is the changelog for `%s`." % version,
                ]
            text_lines = []
            if changelog_lines:
                text_lines.append("Changes captured:")
                text_lines.extend(changelog_lines)
            attachments = [{
                'pretext': "\n".join(pretext_lines),
                'mrkdwn_in': ['pretext', 'text'],
                "text": "\n".join(text_lines),
            }]
            slack_sender = self.bot.slack_sender
            slack_sender.post_send(
                text="Good %s." % self.date_wrangler.get_when(),
                attachments=attachments,
                link_names=True, as_user=True,
                channel=self.message.body.channel,
                log=LOG, thread_ts=self.message.body.get("ts"))
