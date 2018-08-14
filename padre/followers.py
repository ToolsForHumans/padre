import functools
import re

import six

from padre import exceptions as excp
from padre import utils


def ensure_handles(func):

    @six.wraps(func)
    def wrapper(self, handler, message):
        matcher = handler.handles_what.get('message_matcher')
        if matcher is not None:
            if not matcher(message, handler.__class__,
                           only_to_me=False):
                return False
        try:
            handler.check_authorized(handler.bot, message)
        except excp.NotAuthorized:
            return False
        return func(self, handler, message)

    return wrapper


class CancelMe(object):
    cancel_responses = ['cancel', 'stop']

    @ensure_handles
    def __call__(self, handler, message):
        message_text = utils.canonicalize_text(message.body.text)
        if message_text in self.cancel_responses:
            handler.change_state("CANCELLED")
            return True
        return False


class ShowStatus(object):
    state_responses = ['status', 'state']

    @ensure_handles
    def __call__(self, handler, message):
        message_text = utils.canonicalize_text(message.body.text)
        if message_text in self.state_responses:
            replier = functools.partial(message.reply_text,
                                        threaded=True, prefixed=False,
                                        thread_ts=handler.message.body.ts)
            replier("The handler is in `%s` state." % (handler.state))
            return True
        return False


class ConfirmMe(object):
    cancel_responses = ['cancel', 'stop', 'no']
    check_responses = ['check']
    go_responses = ['signoff', 'ok', 'yes', 'go', ':make-it-so:', ':hulk:']
    jfdi_responses = ['jfdi', ':hulk-mad:']
    jfdi_hotdog_re = re.compile(
        r'^\s*(:hotdog:\s*|:gdhotdog:\s*|:hotdogboy:\s*){7}$')

    def __init__(self, confirms_needed=1,
                 confirms_what="???", confirm_self_ok=False,
                 check_func=None):
        self.confirms_forced = set()
        self.confirms = set()
        self.confirms_what = confirms_what
        self.confirms_needed = confirms_needed
        self.confirm_self_ok = confirm_self_ok
        self.check_func = check_func

    def generate_who_satisifies_message(self, handler, quote_char="`"):
        buf = 'Awaiting sign-off from %s members' % self.confirms_needed
        authorizer = handler.handles_what.get("authorizer")
        if authorizer is not None:
            buf += (' that satisfy authorizer'
                    ' %s%s%s') % (quote_char,
                                  authorizer.pformat(handler.bot),
                                  quote_char)
        buf += " to confirm %s%s%s" % (quote_char,
                                       self.confirms_what,
                                       quote_char)
        if self.confirm_self_ok:
            buf += " (self-confirms are ok)"
        else:
            buf += " (self-confirms are not ok)"
        buf += '.'
        return buf

    @classmethod
    def _is_jfdi(cls, message_text):
        if (message_text in cls.jfdi_responses or
                cls.jfdi_hotdog_re.match(message_text)):
            return True
        return False

    @ensure_handles
    def __call__(self, handler, message):
        message_text = utils.canonicalize_text(message.body.text)
        if message_text in self.cancel_responses:
            handler.change_state('CONFIRMED_CANCELLED')
            return True
        who_confirmed = (message.body.user_name, message.body.user_id)
        if self._is_jfdi(message_text):
            self.confirms_forced.add(who_confirmed)
            handler.change_state('CONFIRMED_FORCED')
            return True
        replier = functools.partial(
            message.reply_text, threaded=True, prefixed=True,
            thread_ts=handler.message.body.ts)
        if message_text in self.go_responses:
            what = self.confirms_what
            prior_message_user_name = handler.message.body.user_name
            message_user_name = message.body.user_name
            if ((who_confirmed in self.confirms or
                    # Disallow self-signoffs...
                    message_user_name == prior_message_user_name) and
                    not self.confirm_self_ok):
                authorizer = handler.handles_what.get('authorizer')
                if authorizer is not None:
                    replier("Please get another member"
                            " that satisfies authorizer `%s` to signoff"
                            " on this %s." % (authorizer.pformat(handler.bot),
                                              what))
                else:
                    replier("Please get another member"
                            " to signoff on this %s." % (what))
            else:
                self.confirms.add(who_confirmed)
                if len(self.confirms) >= self.confirms_needed:
                    handler.change_state("CONFIRMED")
        elif (message_text in self.check_responses and
                self.check_func is not None):
            replier(self.check_func())
        else:
            ok_responses = list(self.cancel_responses)
            ok_responses.extend(self.go_responses)
            if self.check_func is not None:
                ok_responses.extend(self.check_responses)
            ok_responses.sort()
            replier("Unexpected confirmation response, please respond"
                    " with one of %s." % (", ".join(ok_responses)))
        return True


class StopExecution(object):
    #: Will eventually trigger a SIGKILL...
    kill_responses = [
        'kill', 'destroy', 'murder',
    ]

    #: Will eventually trigger a SIGINT...
    int_responses = [
        'interrupt', 'int',
        # We will prefer SIGINT over SIGTERM for these (SIGINT usually
        # is nicer and allows for more gracefully shutdown of running
        # programs).
        'stop', 'cancel', 'quit',
    ]

    #: Will eventually trigger a SIGTERM...
    term_responses = [
        'term', 'terminate',
    ]

    @ensure_handles
    def __call__(self, handler, message):
        message_text = utils.canonicalize_text(message.body.text)
        ok_responses = []
        ok_responses.extend(self.kill_responses)
        ok_responses.extend(self.int_responses)
        ok_responses.extend(self.term_responses)
        if (handler.state in ('EXECUTING', 'EXECUTING_KILLED',
                              'EXECUTING_TERM', 'EXECUTING_INTERRUPT') and
                message_text in ok_responses):
            replier = functools.partial(message.reply_text,
                                        threaded=True, prefixed=False,
                                        thread_ts=handler.message.body.ts)
            if message_text in self.kill_responses:
                handler.change_state('EXECUTING_KILLED')
                how_stopped = 'killed (via `SIGKILL`)'
            if message_text in self.int_responses:
                handler.change_state('EXECUTING_INTERRUPT')
                how_stopped = 'interrupted (via `SIGINT`)'
            else:
                handler.change_state('EXECUTING_TERM')
                how_stopped = 'terminated (via `SIGTERM`)'
            replier("Playbook run will hopefully be"
                    " %s soon." % how_stopped)
            return True
        return False
