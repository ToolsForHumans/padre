import logging
import re

import enum
import munch

try:
    from urllib import quote as url_quote
except ImportError:
    from urllib.parse import quote as url_quote

try:
    from urllib import urlencode as url_encode
except ImportError:
    from urllib.parse import urlencode as url_encode

# Slack folks say to keep attachments to less than 20, so we'll
# start splitting into more than one message at 20.
MAX_ATTACHMENTS = 20


class ChannelKind(enum.Enum):
    UNKNOWN = 0
    PUBLIC = 1
    DIRECTED = 2

    @classmethod
    def convert(cls, ch):
        if not ch:
            return cls.UNKNOWN
        if ch[0] in ('C', 'G'):
            return cls.PUBLIC
        if ch[0] in ('D',):
            return cls.DIRECTED
        return cls.UNKNOWN


class Text(object):
    def __init__(self, text):
        self.text = text

    def __repr__(self):
        cls_name = self.__class__.__name__
        return "%s(%r)" % (cls_name, self.text)


class Link(Text):
    def __init__(self, text, link, label=None):
        super(Link, self).__init__(text)
        self.label = label
        self.link = link

    def __repr__(self):
        cls_name = self.__class__.__name__
        if self.label is None:
            return "%s(%r, %r)" % (cls_name, self.text, self.link)
        else:
            return "%s(%r, %r, label=%r)" % (cls_name, self.text,
                                             self.link, self.label)


class CommandLink(Link):
    pass


class ChannelLink(Link):
    pass


class UserLink(Link):
    pass


class HyperLink(Link):
    pass


COLORS = munch.Munch({
    'dark_red': '#8B0000',
    'red': '#FF0000',
    'green': '#008000',
    'orange': '#FFA500',
    'yellow': '#FFFF00',
    'blue': '#0000FF',
    'white': '#FFFFFF',
    'cyan': '#00FFFF',
    'purple': '#800080',
})

LOG_COLORS = {
    logging.CRITICAL: COLORS.dark_red,
    logging.FATAL: COLORS.dark_red,
    logging.ERROR: COLORS.red,
    logging.WARN: COLORS.yellow,
    logging.WARNING: COLORS.yellow,
    logging.INFO: COLORS.green,
    # Maybe just leave these out, but meh, better to be explicit...
    logging.DEBUG: None,
    logging.NOTSET: None,
}

# Some of the errors we know about... (not fully inclusive since
# it appears they change or are added, and we can't fully list them).
#
# PITA...
ERRORS = munch.Munch({
    "ACCOUNT_INACTIVE": "account_inactive",
    "CHANNEL_NOT_FOUND": "channel_not_found",
    "INVALID_ARG_NAME": "invalid_arg_name",
    "INVALID_ARRAY_ARG": "invalid_array_arg",
    "INVALID_AUTH": "invalid_auth",
    "INVALID_CHARSET": "invalid_charset",
    "INVALID_FORM_DATA": "invalid_form_data",
    "INVALID_POST_TYPE": "invalid_post_type",
    "IS_ARCHIVED": "is_archived",
    "MISSING_POST_TYPE": "missing_post_type",
    "MSG_TOO_LONG": "msg_too_long",
    "NOT_AUTHED": "not_authed",
    "NOT_IN_CHANNEL": "not_in_channel",
    "NO_TEXT": "no_text",
    "POSTING_TO_GENERAL_CHANNEL_DENIED": "posting_to_general_channel_denied",

    # Which one of these is correct???
    #
    # https://api.slack.com/methods/chat.postMessage says this is
    # 'rate_limited' but the update message seems to use the other one,
    # arg....
    "RATE_LIMITED": "rate_limited",
    "RATELIMITED": "ratelimited",

    "REQUEST_TIMEOUT": "request_timeout",
    "TOO_MANY_ATTACHMENTS": "too_many_attachments",
})


def is_url_like(blob):
    blob = blob.strip()
    if not blob:
        return False
    if re.match(r"^\s*(\w+)://(.*)\s*$", blob):
        return True
    return False


def insert_quick_link(message, slack_base_url=None):
    # TODO: does the slack api document this format anywhere...
    if (message.kind == 'slack' and
            message.sub_kind == 'message' and slack_base_url and
            message.body.get("ts") and message.body.get('channel')):
        m_link = slack_base_url
        if not m_link.endswith("/"):
            m_link += "/"
        m_link += "archives/%s/" % url_quote(message.body['channel'])
        m_link += "p" + url_quote(message.body['ts'].replace(".", ""))
        m_thread_ts = message.body.get('thread_ts')
        if m_thread_ts:
            m_link += "?"
            m_link += url_encode({
                'thread_ts': m_thread_ts,
            })
        message.body['quick_link'] = m_link


def drop_links(text_pieces, use_label=True, link_classes=(HyperLink,)):
    new_text_pieces = []
    for text_piece in text_pieces:
        if isinstance(text_piece, link_classes):
            if not is_url_like(text_piece.link):
                new_text_pieces.append(text_piece.text)
            else:
                if text_piece.label and use_label:
                    new_text_pieces.append(text_piece.label)
                else:
                    new_text_pieces.append(text_piece.link)
        else:
            new_text_pieces.append(text_piece.text)
    return "".join(new_text_pieces)


def make_mention(user_id):
    return "<@%s>" % (user_id)


def extract_targets(text_pieces):
    targets = []
    last_idx = -1
    for i, text_piece in enumerate(text_pieces):
        if (isinstance(text_piece, Text) and
                not isinstance(text_piece, Link) and
                re.match(r"^(\s+)$", text_piece.text)):
            continue
        if not isinstance(text_piece, UserLink):
            # Stop at anything not a empty text piece or not a user link...
            break
        else:
            target = text_piece.link
            if target not in targets:
                targets.append(target)
            last_idx = i
    if last_idx != -1:
        new_text_pieces = text_pieces[last_idx + 1:]
    else:
        new_text_pieces = text_pieces
    return (targets, list(new_text_pieces))


def parse(text):
    # See: https://api.slack.com/docs/message-formatting
    text_pieces = []
    while text:
        m = re.search("<(.*?)>", text, flags=re.DOTALL | re.UNICODE)
        if not m:
            text_pieces.append(Text(text))
            text = ''
        else:
            start_idx, end_idx = m.span()
            if start_idx != 0:
                text_pieces.append(Text(text[:start_idx]))
            raw = m.group(0)
            raw_contents = m.group(1)
            text = text[end_idx:]
            if raw_contents.startswith("@"):
                raw_contents = raw_contents[1:]
                p_cls = UserLink
            elif raw_contents.startswith("#"):
                raw_contents = raw_contents[1:]
                p_cls = ChannelLink
            elif raw_contents.startswith("!"):
                raw_contents = raw_contents[1:]
                p_cls = CommandLink
            else:
                p_cls = HyperLink
            try:
                raw_contents, label = raw_contents.split("|", 1)
            except ValueError:
                p = p_cls(raw, raw_contents)
            else:
                p = p_cls(raw, raw_contents, label=label)
            text_pieces.append(p)
    return text_pieces


class SlackError(Exception):
    def __init__(self, reason):
        super(SlackError, self).__init__(reason)
        self.reason = reason

    def is_retryable(self):
        if self.reason in (ERRORS.REQUEST_TIMEOUT,
                           ERRORS.RATE_LIMITED,
                           ERRORS.RATELIMITED):
            return True
        return False
