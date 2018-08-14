import fractions


class ManualProgressBar(object):
    """A progress bar you update yourself."""

    def reset(self):
        pass

    def update(self, done_text):
        pass


class AutoProgressBar(object):
    """A progress that updates itself (ie. wrapping some iterator)."""

    def __init__(self, max_am, update_period=1):
        self.max_am = max_am
        self.update_period = update_period
        self._last_am = -1

    def _trigger_change(self, percent_done):
        pass

    def reset(self):
        self._last_am = -1

    def update(self, curr_am):
        curr_am = max(0, min(curr_am, self.max_am))
        should_trigger = False
        if self._last_am == -1:
            should_trigger = True
        else:
            if self._last_am >= 0:
                curr_diff = max(0, curr_am - self._last_am)
                if (curr_diff >= self.update_period or
                        (curr_am == self.max_am and curr_diff != 0)):
                    should_trigger = True
        if should_trigger:
            percent_done = fractions.Fraction(curr_am, self.max_am)
            percent_done = percent_done * 100
            self._trigger_change(percent_done)
            self._last_am = curr_am

    def wrap_iter(self, it):
        self.reset()
        self.update(0)
        for j, item in enumerate(it):
            yield item
            self.update(j + 1)
