import copy

import munch
from oslo_utils import reflection

HEADER_PREFIX = "X-Daddy"
VALIDATED_HEADER = "%s/Validated" % HEADER_PREFIX
TO_ME_HEADER = "%s/To-Self" % HEADER_PREFIX
CHECK_AUTH_HEADER = "%s/Check-Auth" % HEADER_PREFIX
ARGS_HEADER = "%s/ExplicitArgsKwargs" % HEADER_PREFIX
DIRECT_CLS_HEADER = "%s/ExplicitCls" % HEADER_PREFIX
IS_INTERNAL_HEADER = "%s/IsInternal" % HEADER_PREFIX


class Message(object):
    """Sorta like a MIME message, but not..."""

    #: This is used to force chunking of attachments at this amount.
    MAX_ATTACHMENTS = (2 ** 16)

    def __init__(self, raw_kind, headers, body):
        tmp_kind_pieces = raw_kind.split("/", 1)
        self.kind = tmp_kind_pieces[0]
        self.sub_kind = tmp_kind_pieces[1]
        self.body = body
        self.headers = headers

    def __repr__(self):
        cls_name = reflection.get_class_name(self, fully_qualified=False)
        raw_kind = self.kind + "/" + self.sub_kind
        return ("%s('%s', %s, %s)") % (cls_name, raw_kind,
                                       self.headers, self.body)

    def copy(self):
        new_me = copy.copy(self)
        new_me.body = new_me.body.copy()
        new_me.headers = new_me.headers.copy()
        return new_me

    def to_dict(self):
        return {
            'kind': self.kind,
            'sub_kind': self.sub_kind,
            'body': munch.unmunchify(self.body),
            'headers': dict(self.headers),
        }

    def rewrite(self, text_aliases=None):
        return self

    def make_manual_progress_bar(self):
        raise NotImplementedError

    def make_progress_bar(self, max_am, update_period=1):
        raise NotImplementedError

    def reply_attachments(self, attachments, **kwargs):
        raise NotImplementedError

    def reply_text(self, text, **kwargs):
        raise NotImplementedError
