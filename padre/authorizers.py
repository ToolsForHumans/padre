import abc
import itertools

from oslo_utils import reflection
import six

from padre import exceptions as excp
from padre import utils


@six.add_metaclass(abc.ABCMeta)
class auth_base(object):
    """Base of all authorizers."""

    def __and__(self, other):
        return all_must_pass(self, other)

    def __or__(self, other):
        return any_must_pass(self, other)

    @abc.abstractmethod
    def __call__(self, bot, message, args=None):
        pass

    def pformat(self, bot):
        return 'auth_base()'


class no_auth(auth_base):
    """Lets any message through."""

    def pformat(self, bot):
        return 'no_auth()'

    def __call__(self, bot, message, args=None):
        pass


class args_key_is_empty_or_allowed(auth_base):
    """Denies if args key is non-empty and not allowed."""

    def __init__(self, args_key, allowed_extractor_func):
        self.args_key = args_key
        self.allowed_extractor_func = allowed_extractor_func

    def __call__(self, bot, message, args=None):
        if args is None:
            raise excp.NotAuthorized(
                "Message lacks a (non-empty)"
                " 'args' keyword argument, unable to auth against"
                " unknown arguments", message)
        else:
            v = args.get(self.args_key)
            if v:
                allowed_extractor_func = self.allowed_extractor_func
                allowed = allowed_extractor_func(message)
                if v not in allowed:
                    raise excp.NotAuthorized(
                        "Action can not be triggered"
                        " please check that the argument '%s' value is"
                        " allowed or that argument '%s' is"
                        " empty" % (self.args_key, self.args_key))

    def pformat(self, bot):
        base = 'args_key_is_empty_or_allowed'
        func_name = reflection.get_callable_name(self.allowed_extractor_func)
        return '%s(%r, %s)' % (base, self.args_key, func_name)


class user_in_ldap_groups(auth_base):
    """Denies if sending user is not in **config** driven ldap groups."""

    def __init__(self, config_key, *more_config_keys):
        self.config_keys = (config_key,) + more_config_keys

    def pformat(self, bot):
        groups = self._fetch_ok_groups(bot)
        return 'user_in_ldap_groups(%s)' % (utils.quote_join(groups))

    def _fetch_ok_groups(self, bot):
        groups = []
        for k in self.config_keys:
            try:
                val = utils.dict_or_munch_extract(bot.config, k)
            except KeyError:
                pass
            else:
                if isinstance(val, six.string_types):
                    groups.append(val)
                elif isinstance(val, (tuple, list, set)):
                    groups.extend(val)
                else:
                    raise TypeError("Unexpected ldap group"
                                    " configuration value type"
                                    " '%s' corresponding to lookup"
                                    " key: %s" % (type(val), k))
        return groups

    def __call__(self, bot, message, args=None):
        ldap_client = bot.clients.get("ldap_client")
        if not ldap_client:
            raise excp.NotFound("Ldap client not found; required to perform"
                                " authorization checks")
        try:
            user_name = message.body.user_name
        except AttributeError:
            user_name = None
        if not user_name:
            raise excp.NotAuthorized(
                "Message lacks a (non-empty)"
                " user name, unable to auth against"
                " unknown users", message)
        else:
            if not ldap_client.is_allowed(user_name,
                                          self._fetch_ok_groups(bot)):
                raise excp.NotAuthorized(
                    "Action can not be triggered"
                    " please check that the sender is in the correct"
                    " ldap group(s)", message)


class message_from_channels(auth_base):
    """Denies messages not from certain channel name(s)."""

    def __init__(self, channels):
        self.channels = tuple(channels)

    def pformat(self, bot):
        return 'message_from_channels(%s)' % (utils.quote_join(self.channels))

    def __call__(self, bot, message, args=None):
        try:
            channel_name = message.body.channel_name
        except AttributeError:
            channel_name = None
        if not channel_name:
            raise excp.NotAuthorized(
                "Message lacks a (non-empty)"
                " channel name, unable to trigger against"
                " unknown channels", message)
        if channel_name not in self.channels:
            raise excp.NotAuthorized(
                "Action can not be triggered in provided"
                " channel '%s', please make sure that the sender"
                " is in the correct channel(s)" % channel_name, message)


class any_must_pass(auth_base):
    """Combines one or more authorizer (any must pass)."""

    def __init__(self, authorizer, *more_authorizers):
        self.authorizers = tuple(
            itertools.chain([authorizer], more_authorizers))

    def pformat(self, bot):
        others = ", ".join(a.pformat(bot) for a in self.authorizers)
        return 'any_must_pass(%s)' % (others)

    def __call__(self, bot, message, args=None):
        fails = []
        any_passed = False
        for authorizer in self.authorizers:
            try:
                authorizer(bot, message, args=args)
            except excp.NotAuthorized as e:
                fails.append(e)
            else:
                any_passed = True
                break
        if not any_passed and fails:
            # TODO: maybe make a multiple not authorized exception???
            what = " or ".join('(%s)' % e for e in fails)
            raise excp.NotAuthorized(what, message)


class all_must_pass(auth_base):
    """Combines one or more authorizer (all must pass)."""

    def __init__(self, authorizer, *more_authorizers):
        self.authorizers = tuple(
            itertools.chain([authorizer], more_authorizers))

    def pformat(self, bot):
        others = ", ".join(a.pformat(bot) for a in self.authorizers)
        return 'all_must_pass(%s)' % (others)

    def __call__(self, bot, message, args=None):
        for authorizer in self.authorizers:
            authorizer(bot, message, args=args)
