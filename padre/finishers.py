# -*- coding: utf-8 -*-

import logging
import random
import traceback

import futurist
from oslo_utils import encodeutils
from oslo_utils import reflection

from padre import exceptions as excp
from padre import slack_utils as su
from padre import utils

LOG = logging.getLogger(__name__)


class log_on_fail(object):
    """Logs exception to some logger when some future fails."""

    def __init__(self, bot, message, log=None, include_tracebacks=False):
        self.bot = bot
        self.message = message
        if log is not None:
            self.log = log
        else:
            self.log = LOG
        self.include_tracebacks = include_tracebacks

    def _handle_exception(self, e, message):
        self.log.error("Processing %s failed", message,
                       exc_info=bool(self.include_tracebacks))

    def __call__(self, fut):
        try:
            fut.result()
        except futurist.CancelledError:
            pass
        except excp.NoHandlerFound:
            pass
        except excp.Dying:
            pass
        except excp.BaseException as e:
            message = e.message
            if message is None:
                message = self.message
            self._handle_exception(e, message)
        except Exception as e:
            self._handle_exception(e, self.message)


class notify_slack_on_fail(object):
    """Notifies slack (and to some logger) on some future not working out."""

    no_matches_messages = [
        "Sorry %(who)s but I don't know how to do that.",
    ]
    handler_issue_messages = [
        "You seem to have gotten something wrong",
    ]
    generic_issue_messages = [
        'Oopsies, I had a problem handling `%(what)s`.',
    ]
    no_private_messages = [
        ("Sorry %(who)s but I don't like private"
         " messages. Can you please repeat your"
         " request in a public forum/channel. Thanks."),
    ]

    def __init__(self, bot, message,
                 log=None, include_tracebacks=False):
        self.bot = bot
        self.message = message
        self.include_tracebacks = include_tracebacks
        if log is not None:
            self.log = log
        else:
            self.log = LOG

    def _handle_handler_issues_exception(self, e, message):
        self.log.exception("Processing %s had issues", message)
        busted_message = random.choice(self.handler_issue_messages)
        if e.handler_issues:
            busted_message += ":"
        else:
            busted_message += "."
        lines = [busted_message]
        if e.handler_issues:
            lines.append("```")
            lines.append(e.handler_issues)
            lines.append("```")
        try:
            replier = message.reply_text
            replier("\n".join(lines), prefixed=False, threaded=True)
        except Exception:
            self.log.exception("Failed sending message about"
                               " handler issues")

    def _handle_exception(self, e, message):
        self.log.exception("Processing %s failed", message)
        if self.include_tracebacks:
            issue = traceback.format_exc().strip()
        else:
            issue = "%s: %s" % (
                reflection.get_class_name(e, fully_qualified=False),
                encodeutils.exception_to_unicode(e))
        small_issue, smaller_issue = utils.chop(issue)
        if issue:
            attachments = [{
                'fallback': smaller_issue,
                'text': "\n".join([
                    "```",
                    small_issue,
                    "```",
                ]),
                'color': su.COLORS.red,
                'mrkdwn_in': ['text'],
                'footer': 'I broke.',
            }]
        else:
            attachments = []
        # NOTE: Avoid using a reply's ts value; use its parent
        # instead (from slack docs).
        ts = message.body.ts
        if message.body.thread_ts:
            ts = message.body.thread_ts
        oops_message_tpl = random.choice(self.generic_issue_messages)
        oops_message = oops_message_tpl % {'what': message.body.text}
        try:
            replier = message.reply_attachments
            replier(text=oops_message, log=self.log,
                    channel=message.body.channel,
                    thread_ts=ts, as_user=True,
                    unfurl_links=False, link_names=False,
                    attachments=attachments)
        except Exception:
            self.log.exception("Failed sending message about"
                               " processing failure")

    def _handle_no_priv_msg_exception(self, e, message):
        no_priv_message_tpl = random.choice(self.no_private_messages)
        who = su.make_mention(message.body.user_id)
        no_priv_message = no_priv_message_tpl % {'who': who}
        try:
            replier = message.reply_text
            if message.body.thread_ts:
                replier(no_priv_message, threaded=True,
                        thread_ts=message.body.thread_ts,
                        prefixed=False)
            else:
                replier(no_priv_message, threaded=True, prefixed=False)
        except Exception:
            self.log.exception("Failed sending message about"
                               " no private messages")

    def _handle_not_authorized_exception(self, e, message):
        self.log.exception("Processing %s had authorization"
                           " failures", message)
        no_auth_message_tpl = "Sorry %(who)s: %(what)s"
        who = su.make_mention(message.body.user_id)
        no_auth_message = no_auth_message_tpl % {
            'who': who,
            'what': str(e),
        }
        try:
            replier = message.reply_text
            if message.body.thread_ts:
                replier(no_auth_message, threaded=True,
                        thread_ts=message.body.thread_ts,
                        prefixed=False)
            else:
                replier(no_auth_message, threaded=True,
                        prefixed=False)
        except Exception:
            self.log.exception("Failed sending message about"
                               " unauthorized messages")

    def _handle_no_handler_match_exception(self, e, message):
        no_match_message_tpl = random.choice(self.no_matches_messages)
        who = su.make_mention(message.body.user_id)
        no_match_message = no_match_message_tpl % {'who': who}
        if e.suggestion:
            no_match_message += (" Perhaps"
                                 " you meant `%s`?") % e.suggestion
        try:
            replier = message.reply_text
            if message.body.thread_ts:
                replier(no_match_message, threaded=True,
                        thread_ts=message.body.thread_ts, prefixed=False)
            else:
                replier(no_match_message, threaded=False, prefixed=False)
        except Exception:
            self.log.exception("Failed sending message about"
                               " no handler match")

    def __call__(self, fut):
        try:
            fut.result()
        except futurist.CancelledError:
            pass
        except excp.NoFollowupHandlerFound:
            # Follow up messages that we don't match we just drop, because
            # they may or may not be for this bot, and we don't have the full
            # history of slack loaded, so we don't really know...
            pass
        except excp.Dying:
            pass
        except excp.NotAuthorized as e:
            message = e.message
            if message is None:
                message = self.message
            self._handle_not_authorized_exception(e, message)
        except excp.NoPrivateMessage as e:
            message = e.message
            if message is None:
                message = self.message
            self._handle_no_priv_msg_exception(e, message)
        except excp.NoHandlerFound as e:
            message = e.message
            if message is None:
                message = self.message
            self._handle_no_handler_match_exception(e, message)
        except excp.HandlerReportedIssues as e:
            message = e.message
            if message is None:
                message = self.message
            self._handle_handler_issues_exception(e, message)
        except excp.BaseException as e:
            message = e.message
            if message is None:
                message = self.message
            self._handle_exception(e, message)
        except Exception as e:
            self._handle_exception(e, self.message)
