# -*- coding: utf-8 -*-

import abc
import logging

from apscheduler.triggers import cron
import munch
from oslo_utils import excutils
from oslo_utils import reflection
from oslo_utils import strutils
from oslo_utils import timeutils
import six
from voluptuous import humanize
from voluptuous import Invalid

from padre import exceptions as excp
from padre import followers as f
from padre import matchers
from padre import message as m
from padre import mixins
from padre import periodic_utils as peu
from padre import utils

LOG = logging.getLogger(__name__)


def _fetch_thing_from_munch(where, what, tolerant=True):
    try:
        thing = where[what]
    except KeyError:
        if tolerant:
            thing = munch.Munch()
        else:
            raise
    return thing


class HandlerABCMeta(abc.ABCMeta):
    def __new__(cls, name, parents, dct):
        # Ensure that *each* class that is derived from this has its
        # *own* copy of these stats (we do not want each class to share
        # the same stats dictionary, since that would be bad...); do note
        # that we did initially put this as a class level variable, but
        # that causes all subclasses to share the same stats (which wasn't
        # wanted).
        dct['stats'] = munch.Munch({
            'ran': 0,
            'failed': 0,
            'total_run_time': 0,
        })
        return super(HandlerABCMeta, cls).__new__(cls, name, parents, dct)


class HandlerMatch(object):
    def __init__(self, arguments=''):
        self.arguments = arguments


class ExplicitHandlerMatch(object):
    def __init__(self, arguments=None):
        if arguments is not None:
            self.arguments = arguments.copy()
        else:
            self.arguments = {}


@six.add_metaclass(HandlerABCMeta)
class Handler(mixins.TemplateUser):
    config_section = None
    secret_section = None
    template_subdir = None
    handles_what = {
        'message_matcher': matchers.match_none,
        'channel_matcher': matchers.match_none,
    }

    # See: is_enabled to know what these do.
    config_on_off = None
    required_configurations = None
    required_secrets = None
    required_calendars = None
    required_clients = None
    requires_slack_sender = False
    requires_topo_loader = False

    def __init__(self, bot, message):
        self.bot = bot
        self.date_wrangler = bot.date_wrangler
        self.dead = bot.dead
        self.message = message
        self.config = self.fetch_config(bot)
        self.secrets = self.fetch_secrets(bot)
        self.state_history = []
        self.state = None
        self.template_dirs = list(bot.config.get("template_dirs", []))
        self.watch = timeutils.StopWatch()
        self.created_on = self.date_wrangler.get_now()
        self.followers = [
            # This one is always used/included...
            f.ShowStatus(),
        ]
        for f_cls in self.handles_what.get('followers', []):
            self.followers.append(f_cls())

    def change_state(self, target_state):
        self.state_history.append((self.state, target_state))
        self.state = target_state

    @staticmethod
    def _format_voluptuous_error(data, validation_error,
                                 max_sub_error_length=500):
        """Turns a voluptuous invalid data error into something more readable."""  # noqa: E501
        return humanize.humanize_error(
            data, validation_error,
            max_sub_error_length=max_sub_error_length)

    @classmethod
    def setup_class(cls, bot):
        pass

    @classmethod
    def insert_periodics(cls, bot, scheduler):
        pass

    @classmethod
    def is_enabled(cls, bot):
        cls_name = reflection.get_class_name(cls, fully_qualified=True)
        nice_cls_name = "Handler '%s'" % cls_name
        try:
            cls_conf = cls.fetch_config(bot, tolerant=False)
        except KeyError:
            LOG.warn("%s has been disabled, missing required"
                     " configuration section '%s'",
                     nice_cls_name, cls.config_section)
            return False
        try:
            cls_sec_conf = cls.fetch_secrets(bot, tolerant=False)
        except KeyError:
            LOG.warning("%s has been disabled, missing required"
                        " secret section '%s'",
                        nice_cls_name, cls.secret_section)
            return False
        if cls.config_on_off is not None:
            try:
                on = utils.dict_or_munch_extract(
                    cls_conf, cls.config_on_off[0])
            except KeyError:
                on = cls.config_on_off[1]
            if not strutils.bool_from_string(on):
                LOG.warn("%s has been disabled, forced off"
                         " by configuration value at path '%s'",
                         nice_cls_name, cls.config_on_off[0])
                return False
        lookups = []
        if cls.required_configurations:
            lookups.append(("configuration", cls_conf,
                            sorted(cls.required_configurations)))
        if cls.required_secrets:
            lookups.append(("secret", cls_sec_conf,
                            sorted(cls.required_secrets)))
        for lookup_name, lookup_root, lookup_paths in lookups:
            for lookup_path in lookup_paths:
                try:
                    utils.dict_or_munch_extract(lookup_root, lookup_path)
                except KeyError:
                    LOG.warn("%s has been disabled, missing required"
                             " %s under path '%s'", nice_cls_name,
                             lookup_name, lookup_path)
                    return False
                except TypeError:
                    LOG.warn("%s has been disabled, missing correct"
                             " type of %s under path '%s'", nice_cls_name,
                             lookup_name, lookup_path)
                    return False
        if cls.required_clients:
            for client_name in sorted(cls.required_clients):
                # TODO: fix this...
                real_client_name = client_name + "_client"
                client = bot.clients.get(real_client_name)
                if client is None:
                    LOG.warn("%s has been disabled, missing required"
                             " '%s' client", nice_cls_name, client_name)
                    return False
        if cls.required_calendars:
            for calendar_name in sorted(cls.required_calendars):
                cal = bot.calendars.get(calendar_name)
                if cal is None:
                    LOG.warn("%s has been disabled, missing required"
                             " '%s' calendar", nice_cls_name, calendar_name)
                    return False
        if cls.requires_topo_loader and bot.topo_loader is None:
            LOG.warn("%s has been disabled, missing required"
                     " topology loader", nice_cls_name)
            return False
        if cls.requires_slack_sender and bot.slack_sender is None:
            LOG.warn("%s has been disabled, missing required"
                     " slack sender", nice_cls_name)
            return False
        return True

    @classmethod
    def fetch_config(cls, bot, tolerant=True):
        if cls.config_section:
            config = _fetch_thing_from_munch(bot.config,
                                             cls.config_section,
                                             tolerant=tolerant)
        else:
            config = bot.config
        return config

    @classmethod
    def fetch_secrets(cls, bot, tolerant=True):
        if cls.secret_section:
            secrets = _fetch_thing_from_munch(bot.secrets,
                                              cls.secret_section,
                                              tolerant=tolerant)
        else:
            secrets = bot.secrets
        return secrets

    @abc.abstractmethod
    def _run(self, *args, **kwargs):
        pass

    def run(self, match):
        with self.watch:
            self.change_state("PARSING")
            try:
                args, validated = self.extract_arguments(match)
            except ValueError as e:
                self.change_state("PARSING_FAILED")
                raise excp.HandlerReportedIssues(
                    self.__class__, str(e), message=self.message)
            self.change_state("VALIDATING")
            if not validated:
                try:
                    self.validate_arguments(args)
                except ValueError as e:
                    self.change_state("VALIDATING_FAILED")
                    raise excp.HandlerReportedIssues(
                        self.__class__, str(e), message=self.message)
            self.change_state("AUTHORIZING")
            try:
                self.check_authorized(self.bot, self.message, args=args)
            except Exception:
                with excutils.save_and_reraise_exception():
                    self.change_state("AUTHORIZING_FAILED")
            self.change_state("MANIPULATING")
            try:
                self.manipulate_arguments(args)
            except ValueError as e:
                self.change_state("MANIPULATING_FAILED")
                raise excp.HandlerReportedIssues(
                    self.__class__, str(e), message=self.message)
            self.change_state("RUNNING")
            try:
                result = self._run(**args)
            except Exception:
                with excutils.save_and_reraise_exception():
                    self.change_state(self.state + "_SADLY_FAILED")
            else:
                self.change_state(self.state + "_HAPPILY_FINISHED")
                return result

    @staticmethod
    def manipulate_arguments(args):
        """Used to futher 'massage' arguments after validating/authorizing."""
        pass

    @classmethod
    def check_authorized(cls, bot, message, args=None):
        check_auth = message.headers.get(m.CHECK_AUTH_HEADER, True)
        if check_auth:
            authorizer = cls.handles_what.get("authorizer")
            if authorizer is not None:
                authorizer(bot, message, args=args)

    def wait_for_transition(self, follower=None, wait_timeout=None,
                            wait_check_delay=0.1,
                            wait_start_state='SUSPENDED',
                            reset_prior_state=False):
        old_state = self.state
        try:
            if follower is not None:
                self.followers.append(follower)
            self.change_state(wait_start_state)
            moved = True
            with timeutils.StopWatch(duration=wait_timeout) as w:
                while self.state == wait_start_state:
                    if w.expired() or self.dead.is_set():
                        moved = False
                        break
                    delay = wait_check_delay
                    try:
                        delay = min(w.leftover(), delay)
                    except RuntimeError:
                        pass
                    self.dead.wait(delay)
            if reset_prior_state:
                self.change_state(old_state)
            if not moved and self.dead.is_set():
                raise excp.Dying
            if not moved and w.expired():
                raise excp.WaitTimeout(w.elapsed())
        finally:
            if follower is not None:
                try:
                    self.followers.remove(follower)
                except ValueError:
                    pass

    @classmethod
    def validate_arguments(cls, args):
        try:
            args_def = cls.handles_what['args']
        except KeyError:
            pass
        else:
            args_schema = args_def.get("schema")
            if args_schema is not None:
                try:
                    args_schema(args)
                except Invalid as e:
                    raise ValueError(cls._format_voluptuous_error(args, e))

    @classmethod
    def extract_arguments(cls, match):
        if isinstance(match, ExplicitHandlerMatch):
            args = match.arguments
            try:
                args_def = cls.handles_what['args']
            except KeyError:
                args_def = {}
            args_defaults = args_def.get("defaults", {})
            for k, v in args_defaults.items():
                if k not in args:
                    args[k] = v
            return args, True
        else:
            try:
                args_def = cls.handles_what['args']
            except KeyError:
                args = {}
            else:
                args = utils.extract_args(
                    match.arguments, args_def.get('order', []),
                    args_defaults=args_def.get('defaults', {}),
                    args_converters=args_def.get('converters', {}),
                    args_accumulate=args_def.get("accumulate", set()),
                    allow_extras=args_def.get("allow_extras", False))
            return args, False

    @classmethod
    def handles(cls, message, channel, config):
        channel_matcher = cls.handles_what['channel_matcher']
        if not channel_matcher(channel):
            return None
        message_matcher = cls.handles_what['message_matcher']
        if message_matcher(message, cls):
            if m.ARGS_HEADER in message.headers:
                args = message.headers[m.ARGS_HEADER]
                return ExplicitHandlerMatch(arguments=args)
            else:
                return HandlerMatch()
        return None

    @staticmethod
    def has_help():
        return False

    @staticmethod
    def get_help(bot):
        return ("", "")


class TriggeredHandler(Handler):
    # Config path (period separated) that will have details about
    # how to configure this handler to be a periodic (with at least
    # a period attribute defining a valid apscheduler cron period) with
    # optional attributes [channel, name, id, description].
    periodic_config_path = None

    @classmethod
    def handles(cls, message, channel, config):
        channel_matcher = cls.handles_what['channel_matcher']
        if not channel_matcher(channel):
            return None
        message_matcher = cls.handles_what['message_matcher']
        if message_matcher(message, cls):
            if m.ARGS_HEADER in message.headers:
                args = message.headers[m.ARGS_HEADER]
                return ExplicitHandlerMatch(arguments=args)
            try:
                message_text = message.body.text_no_links
            except AttributeError:
                message_text = message.body.text
            for trig in cls.handles_what.get("triggers", []):
                matches, arguments = trig.match(message_text)
                if matches:
                    return HandlerMatch(arguments=arguments)
        return None

    @classmethod
    def insert_periodics(cls, bot, scheduler):
        if not cls.periodic_config_path:
            return
        slack_client = bot.clients.get("slack_client")
        slack_sender = bot.slack_sender
        # TODO: make these optional and work without these (for say
        # when slack not connected or something...)
        if not all([slack_client, slack_sender]):
            return
        try:
            p_list = utils.dict_or_munch_extract(bot.config,
                                                 cls.periodic_config_path)
        except KeyError:
            pass
        else:
            cls_name = reflection.get_class_name(cls)
            runs_what = "handler '%s'" % cls_name
            for i, p in enumerate(p_list):
                runner_channel = (
                    p.get("channel") or
                    bot.config.get('periodic_channel') or
                    bot.config.admin_channel
                )
                runner = peu.make_periodic_runner(
                    runs_what, cls, p.period, runner_channel, log=LOG)
                runner_trigger = cron.CronTrigger.from_crontab(
                    p.period, timezone=bot.config.tz)
                runner.__module__ = getattr(cls, '__module__', __name__)
                runner_name = p.get("name", cls_name + ".run()")
                runner_description = p.get("description") or "\n".join([
                    "Periodic run of %s" % runs_what,
                    "",
                    "To channel: %s" % runner_channel,
                    "",
                    "With period: %s" % p.period,
                ])
                runner_id = p.get("id") or utils.hash_pieces(
                    [runner_name, runner_description, p.period,
                     str(i)], max_len=8)
                scheduler.add_job(
                    runner, trigger=runner_trigger,
                    jobstore='memory', coalesce=True,
                    name="\n".join([runner_name, runner_description]),
                    id=runner_id, args=(bot, slack_client, slack_sender))

    @classmethod
    def has_help(cls):
        cls_triggers = cls.handles_what.get('triggers', [])
        if cls_triggers:
            return True
        else:
            return False

    @classmethod
    def get_help(cls, bot):
        how_to = []
        indent = "    "

        lines = []
        cls_triggers = cls.handles_what.get('triggers', [])
        if len(cls_triggers) > 1:
            lines.append("_Triggers:_")
            for cls_trigger in cls_triggers:
                lines.append(indent + u"• *%s*" % (cls_trigger.text))
        elif len(cls_triggers) == 1:
            lines.append("_Trigger:_ *%s*" % cls_triggers[0].text)
        how_to.extend(lines)

        args = cls.handles_what.get('args', {})
        args_order = args.get('order', [])
        args_defaults = args.get('defaults', {})
        args_help = args.get("help", {})

        lines = []
        if args_order:
            how_to.append("_Arguments:_")
            for arg in args_order:
                if arg in args_defaults:
                    arg_default = args_defaults[arg]
                    if arg_default is None:
                        arg_default = ""
                    if arg_default != "":
                        arg_default = "`%s`" % arg_default
                    lines.append("%s`%s` (default=%s) " % (indent, arg,
                                                           arg_default))
                else:
                    lines.append("%s`%s` (required) " % (indent, arg))
            how_to.extend(lines)

        lines = []
        for arg in args_order:
            if arg in args_help:
                # Only take the first line (if there are many).
                help = args_help[arg]
                help = help.splitlines()[0]
                if help:
                    lines.append("%s`%s`: %s" % (indent, arg, help))
        if lines:
            how_to.append("_Argument help:_")
            how_to.extend(lines)

        authorizer = cls.handles_what.get("authorizer")
        if authorizer is not None:
            how_to.append("_Authorizer:_ `%s`" % authorizer.pformat(bot))

        if cls.__doc__:
            title = cls.__doc__.splitlines()[0].strip()
        else:
            title = "???"

        return (title, how_to)
