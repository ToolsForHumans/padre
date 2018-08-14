# -*- coding: utf-8 -*-

import copy
import logging

import munch

from padre import channel as c
from padre import handler
from padre import matchers
from padre import trigger
from padre import utils

LOG = logging.getLogger(__name__)


class Handler(handler.TriggeredHandler):
    """Shows you what this bots current config is."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('show config', takes_args=False),
            trigger.Trigger('config show', takes_args=False),
        ],
    }

    def _run(self, **kwargs):
        tmp_config = copy.deepcopy(self.bot.config)
        tmp_config = munch.unmunchify(tmp_config)
        tmp_config = utils.mask_dict_password(tmp_config)
        tmp_config = utils.prettify_yaml(tmp_config,
                                         explicit_end=False,
                                         explicit_start=False)
        lines = []
        lines.append("I am running with configuration:")
        lines.extend([
            "```",
            tmp_config,
            "```",
        ])
        replier = self.message.reply_text
        replier("\n".join(lines), threaded=True, prefixed=True)
