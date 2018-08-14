import six

from voluptuous import Any
from voluptuous import Invalid


def one_of(ok_values):
    def _one_of(val):
        if val not in ok_values:
            if len(ok_values) == 0:
                raise Invalid("Nothing is allowed.")
            if len(ok_values) == 1:
                raise Invalid("Only '%s' is allowed." % ok_values[0])
            raise Invalid("One of '%s' expected." % ", ".join(ok_values))
    return _one_of


def string_types():
    return Any(*six.string_types)
