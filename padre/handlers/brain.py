# -*- coding: utf-8 -*-

import logging

import munch

from padre import channel as c
from padre import handler
from padre import matchers
from padre import trigger
from padre import utils

LOG = logging.getLogger(__name__)


def _resolve_slack_user(bot, user):
    # This handles internally finding by name or id...
    real_user_id = None
    real_user_name = None
    try:
        slack_client = bot.clients.slack_client
    except AttributeError:
        pass
    else:
        real_user = slack_client.server.users.find(user)
        if real_user:
            real_user_id = real_user.id
            real_user_name = real_user.name
    return (real_user_id, real_user_name)


def _resolve_user(bot, message, user=''):
    real_user_id = None
    real_user_name = None
    if not user:
        real_user_id = message.body.get("user_id")
        real_user_name = message.body.get("user_name")
    else:
        if message.kind == 'slack':
            real_user_id, real_user_name = _resolve_slack_user(bot, user)
    if not real_user_name and real_user_id:
        real_user_name = real_user_id
    return munch.Munch({
        'id': real_user_id,
        'name': real_user_name,
    })


def _extract_ok_user(message):
    allowed = set()
    for k in ('user_name', 'user_id'):
        u_v = message.body.get(k)
        if u_v:
            allowed.add(u_v)
    return allowed


class DumpHandler(handler.TriggeredHandler):
    """Dumps what is in the bots brain about a given user."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('brain dump', takes_args=True),
        ],
        'args': {
            'order': [
                'user',
            ],
            'defaults': {
                'user': "",
            },
            'help': {
                'user': ("user id or user name"
                         " to dump (leave empty to dump calling user)"),
            },
        },
    }

    def _fetch_known(self, real_user):
        user_memory = {}
        with self.bot.locks.brain:
            alias_key = "user:%s" % real_user.id
            try:
                user_memory['aliases'] = dict(self.bot.brain[alias_key])
            except KeyError:
                pass
        return user_memory

    def _run(self, user=''):
        real_user = _resolve_user(self.bot, self.message, user=user)
        replier = self.message.reply_text
        if not real_user.id:
            if user:
                replier("Unable to find user `%s`." % user,
                        threaded=True, prefixed=False)
            else:
                replier("Unable to find calling user.",
                        threaded=True, prefixed=False)
        else:
            if not user:
                user = real_user.name
            if not user:
                user = real_user.id
            user_memory = self._fetch_known(real_user)
            if not user_memory:
                replier("Nothing internalized about `%s`." % user,
                        threaded=True, prefixed=True)
            else:
                lines = []
                lines.append("I have internalized the"
                             " following about `%s`:" % user)
                user_memory = utils.prettify_yaml(
                    utils.mask_dict_password(user_memory),
                    explicit_end=False, explicit_start=False)
                lines.extend([
                    "```",
                    user_memory.strip(),
                    "```",
                ])
                replier("\n".join(lines), threaded=True, prefixed=False)
