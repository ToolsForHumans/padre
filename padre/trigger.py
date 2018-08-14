import re


def _clean_text(text):
    text = text.lower()
    text_pieces = re.split(r"\s+", text)
    text = " ".join(text_pieces)
    return text.strip()


class Trigger(object):
    def __init__(self, text, takes_args=False):
        self._text = _clean_text(text)
        self._matcher = self._compile_matcher(self._text, takes_args)
        self._takes_args = takes_args

    @property
    def text(self):
        return self._text

    @property
    def takes_args(self):
        return self._takes_args

    @property
    def matcher(self):
        return self._matcher

    def __eq__(self, other):
        if not isinstance(other, Trigger):
            return NotImplemented
        return (self.text, self.takes_args) == (other.text, other.takes_args)

    def __hash__(self):
        if self.takes_args:
            return hash(self.text) * 11
        else:
            return hash(self.text) * 13

    @staticmethod
    def _compile_matcher(text, takes_args):
        trigger_pieces = re.split(r"\s+", text)
        for i, piece in enumerate(trigger_pieces):
            tmp_piece = re.escape(piece)
            if i + 1 != len(trigger_pieces):
                tmp_piece = tmp_piece + r"\s+"
            trigger_pieces[i] = tmp_piece
        trigger = "".join(trigger_pieces)
        trigger = r"^\s*" + trigger
        if takes_args:
            trigger = trigger + r"(?:(\s+.+)|(\s*))$"
        else:
            trigger = trigger + r"\s*$"
        return re.compile(trigger, re.I)

    def match(self, in_text):
        m = self._matcher.match(in_text)
        if not m:
            return (False, '')
        else:
            if self._takes_args:
                args = m.group(1)
                if not args:
                    args = m.group(2)
                if not args:
                    args = ''
                return (True, args.strip())
            else:
                return (True, '')
