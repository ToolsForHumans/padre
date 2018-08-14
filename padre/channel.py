import enum


class Channel(enum.Enum):
    """Channel messages go to."""

    BROADCAST = 1
    """
    All handlers that can process a given message will be allowed to, any
    that fail will not cause further to fail.
    """

    FOLLOWUP = 2
    """
    This is a special case of a prior targeted message, in that only a
    still active previously targeted handler can recieve a followup
    message.
    """

    TARGETED = 3
    """
    A message targeted for a single handler and that will be handled
    by only-one handler (assuming a match is found); if that handler fails
    no other handlers will be tried.
    """


# Makes these easier to access; without having to
# go into the channel class (since we are already in a channel
# module...)
BROADCAST = Channel.BROADCAST
FOLLOWUP = Channel.FOLLOWUP
TARGETED = Channel.TARGETED
