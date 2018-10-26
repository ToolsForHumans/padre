Get your app and token
----------------------

1. Make a slack app for your environment and add the integration to
   your environment and invite the user you make into a test-bot channel.

2. Ensure that you get the bot user oauth access token from your bots
   oauth and permissions page, typically located at a URL like
   https://api.slack.com/apps/<BOT_ID>/oauth

3. Place that token in conf/dev/base.yaml like::

     slack:
       token: <the-token>
       base_url: http://<your-env>.slack.com/

Install the bot
---------------

In your bot folder setup a virtualenv (python 2.7)::

   virtualenv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install -e .

Run the bot
-----------

Then run your bot::

   # This isn't needed (unless u are using secrets, but code
   # wants it, for now, so it can be a fake value)
   export DADDY_PASS=abc123
   export BOT_PRODUCTION=0
   export BOT=<your-bot-name>
   bash scripts/start.sh

**Profit!**
