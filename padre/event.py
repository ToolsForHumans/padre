import threading

from oslo_utils import reflection


class Event(object):
    """Event like object that allows for associating a useful value."""

    NOT_SET = 0
    RESTART = 2
    DIE = 1

    _STATE_TO_NAME = {
        NOT_SET: 'NOT_SET',
        RESTART: 'RESTART',
        DIE: 'DIE',
    }

    def __init__(self):
        self._cond = threading.Condition()
        self._val = self.NOT_SET

    def __repr__(self):
        return "<%s object at 0x%x: %s>" % (
            reflection.get_class_name(self),
            id(self), self._STATE_TO_NAME[self._val])

    def set(self, val=DIE):
        if val not in (self.DIE, self.RESTART):
            ok_vals = (self._STATE_TO_NAME[self.DIE],
                       self._STATE_TO_NAME[self.RESTART])
            raise ValueError("Invalid value, only %s or %s"
                             " are allowed" % ok_vals)
        with self._cond:
            self._val = val
            self._cond.notify_all()

    def wait(self, timeout=None):
        with self._cond:
            if self._val == self.NOT_SET:
                self._cond.wait(timeout=timeout)
            return self.is_set()

    @property
    def value(self):
        return self._val

    def is_set(self):
        return self._val != self.NOT_SET

    def clear(self):
        with self._cond:
            self._val = self.NOT_SET
