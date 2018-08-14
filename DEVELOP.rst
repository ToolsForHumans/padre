---------------------------
How this thing be developed
---------------------------

Configuring
-----------

So this program has access to three main configuration files (two are
merged into one when the program starts). Let's do a short overview of
each of these files and how it relates to the overall program.

**conf/base.yaml**

These are the main bot configuration that lists **non-secret** configuration
value and settings (including things like logging configuration). Important
values including endpoint names in here (including the bot endpoint and
where ara endpoint is and such); but none of this is secret and so it is
in here.

**conf/secrets.yaml**

These are also part of the main bot configuration (and it is merged into
the prior configuration when loaded into memory and both become
available to all parts of the program; and both are displayed publicly
in the configuration json endpoint, with secret values replaced
with ``***`` in this endpoint). It is in ansible vault inline secret format
and requires ansible to be able to decode correctly
(it uses AES256 ya da ya da). It typically has things like a slack bot token
in it, jira user and password, elastic user and password and various other
bot-specific secrets that are used for various handlers. Once loaded all of
the above show up in the ``bot.config`` attribute (and handlers can access this
or request that they only see a certain *namespace* of that configuration).

To have other yaml ansible-vault *secret* files that do **not** show up in
the json endpoints you can pass those in via the ``-s`` command line
argument (they will get loaded and stored in a ``bot.secrets`` attribute).

Getting it installed
--------------------

Update your pip configuration to make sure it can find all the needed
packages.

After that follow these directions:

Option one:

* A python 2.7 virtualenv (create one).
* Install ``requirements.txt`` and ``test-requirements.txt`` into
  that virtualenv.
* Run ``pip install -e .`` to get the bot program installed.

Option two:

* Get `tox`_ installed.
* Run ``tox -epy27``.

Next steps:

* Create a slack bot token (or ask someone that knows how to make
  one so that you can get a slack bot online). This is somewhat
  convoluted to do but search google and `slack`_ has the ability
  to do this (though it is not easy to discover how).
* Create a new ``conf/${your_bot_name}/secrets.yaml`` configuration for
  your slack token and put the token under section ``slack/token``.
* Create ``conf/${your_bot_name}/base.yaml`` and then adjust as/if needed.
* Create or adjust ``conf/base.yaml`` or ``conf/secrets.yaml``
  or ``conf/dev/base.yaml`` or ``conf/dev/secrets.yaml`` as/if needed (use
  the ``prod`` folder for production settings).

  * Change ``DADDY_PASS`` in your environment to match these files new
    password (if applicable).

Run via (or similar)::

     daddy -c $PWD/conf/:DADDY_PASS \
           -c $PWD/conf/dev/:DADDY_PASS \
           -c $PWD/conf/${your_bot_name}/:DADDY_PASS

If you need to bootstrap the required ansible, ara, and other system
configuration files then you should run the following **before**
the prior command::

     daddy -c $PWD/conf/:DADDY_PASS \
           -c $PWD/conf/dev/:DADDY_PASS \
           -c $PWD/conf/${your_bot_name}/:DADDY_PASS \
           --just-bootstrap

The ``scripts/start.sh`` bash script (the same one the container uses) can
also be used to do both of these; so try it out if the above is to
complicated (you will have to export your bot name ``${your_bot_name}`` under
the environment variable ``BOT`` for this script to start correctly).

Making your first handler
-------------------------

Ok so you want the bot to process some slack message and do something
with it, let's assume that for starters you want to have the bot perform
some simple calculator like functionality where it can add two numbers.

First we need to define how that action will triggered (ie, what prefix
text will activate the logic to do this calculation) and then we need to
specify what arguments come in to that action.

To start make a new module (we will call it ``calculator.py``) under
``padre/handlers`` with the following content::

    from padre import handler

    class AddHandler(handler.TriggeredHandler):
        def _run(self, **kwargs):
            pass

Congratulations, you have just made a bare minimum handler (that will not
do anything); as you can see you must provide a ``_run`` (which will do
whatever logic we desire) and you must inherit from the right base class.

Next up we will define a ``handles_what`` dictionary that will tell the
surrounding bot engine
how to route messages to this ``_run`` method and what arguments, schema, and
triggers will activate this method (this lets you the handler creator focus
on your `_run` method and not on argument validation, parsing, and such)::

    from voluptuous import All
    from voluptuous import Range
    from voluptuous import Schema

    from padre import authorizers
    from padre import channel as c
    from padre import handler
    from padre import matchers
    from padre import trigger

    class AddHandler(handler.TriggeredHandler):
        handles_what = {
            # We only want to get slack messages that are of
            # type 'message' (there are
            # other types like 'user_typing' and such, but we do not want to
            # be routed those).
            'matcher': matchers.match_slack("message"),
            # We want to be called when this trigger matches.
            'triggers': [
                trigger.Trigger("calculator add", takes_args=True),
            ],
            # We do not want to receive broadcast messages (but only
            # get things that are flowing on the targeted worker queue);
            # the primary difference is that on the targeted worker queue
            # a single handler match happens, while on the broadcast channel
            # many handler matches can happen (and the failure handling is
            # different due to that).
            'channel_matcher': matchers.match_channel(c.TARGETED),
            # If we want to restrict (post argument extraction who can
            # call this run method, then you can provide an authorizer
            # object here).
            'authorizer': authorizers.no_auth(),
            # Any arguments we want to get automatically extracted go in here.
            'args': {
                # The positional order in which arguments are mapped (when
                # not passed in a keyword argument style) from user input.
                'order': [
                    'num1',
                    'num2',
                ],
                # If we want to do any conversions of the arguments before
                # schema validation (and before _run) we can provide any
                # callable here to do so.
                'converters': {
                    # These need to take a raw string and produce a better
                    # value (or raise a value error or other if they can
                    # not do so).
                    'num1': int,
                    'num2': int,
                },
                # When the special help handler is called it will use this
                # attribute (and the handler ``get_help`` method) to generate
                # a useful help message (so users know what the arguments
                # are).
                'help': {
                    'num1': "first number (positive integer)",
                    'num2': "second number (positive integer)",
                },
                # Once converting has been performed we can do a final
                # schema validation pass to ensure that we have any other
                # checks/conditions to apply to ensure the arguments are just
                # like we want them.
                'schema': Schema({
                    'num1': All(int, Range(min=0)),
                    'num2': All(int, Range(min=0)),
                }),
            },
        }

        def _run(self, **kwargs):
            total = kwargs['num1'] + kwargs['num2']
            # This message object is the message that actually came to
            # this handler (it includes nice helpers to be able to reply
            # as well as a body attribute that can be used to look at
            # various other attributes that may have came along with the
            # message).
            self.message.reply_text(
                "Total = %s" % total,
                # This will cause the reply to go to a subthread of the
                # original message (slack supports the concept of one level
                # subthreads); if this is false, then the message just goes
                # into the channel that the initiating message came from.
                threaded=True,
                # When this is provided; the actual message will be prefixed
                # with the user who initiated the message (making it easier
                # for the caller to know the message is for them).
                prefixed=True)

There you have it, an adder that gets some arguments, converts them,
validates them, and then tells the user what the total of those
two numbers are. Pretty amazing right!

.. _slack: https://www.slack.com/
.. _tox: https://tox.readthedocs.io/
.. _ara: https://ara.readthedocs.io
