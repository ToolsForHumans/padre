import os
import tempfile

import mock
import munch
import six

from padre import date_utils as du
from padre import event as e
from padre import message as m


class DummyEvent(e.Event):
    def wait(self, timeout=None):
        pass


class DummyLock(object):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, tb):
        pass


def make_message(text, ts=1, thread_ts=None,
                 to_me=False, user_id=None, user_name=None,
                 channel=None, channel_name=None,
                 kind="slack", sub_kind="message",
                 check_auth=False):
    m_headers = {
        m.VALIDATED_HEADER: True,
        m.CHECK_AUTH_HEADER: check_auth,
        m.TO_ME_HEADER: to_me,
    }
    m_body = munch.Munch({
        'text': text,
        'text_no_links': text,
        'ts': ts,
        'thread_ts': thread_ts,
        'user_id': user_id,
        'user_name': user_name,
        'channel': channel,
        'channel_name': channel_name,
    })
    mm = mock.create_autospec(m.Message, instance=True)
    mm.MAX_ATTACHMENTS = 256
    mm.kind = kind
    mm.sub_kind = sub_kind
    mm.body = m_body
    mm.headers = m_headers
    return mm


def make_bot(user="AwesomeUser", password="somepassword",
             simple_config=False):
    bot = mock.MagicMock()
    bot.topo_loader = mock.MagicMock()
    bot.config = munch.Munch()
    bot.config.user = user
    bot.config.password = password
    if not simple_config:
        bot.config.plugins = munch.Munch()
        bot.config.ansible = munch.Munch()
        bot.config.ansible.playbooks = {}
        bot.config.ansible.inventories = {}
        bot.config.template_dirs = [os.path.join(os.getcwd(), 'templates')]
        bot.config.working_dir = tempfile.gettempdir()
        bot.config.playbook_dir = tempfile.gettempdir()
        bot.config.persistent_working_dir = tempfile.gettempdir()
        bot.config.statics_dir = tempfile.gettempdir()
        bot.config.env_dir = "."
        bot.config.github = munch.Munch()
        bot.config.github.hook = munch.Munch()
        bot.config.github.hook.port = 65534
        bot.config.sensu = munch.Munch()
        bot.config.sensu.hook = munch.Munch()
        bot.config.sensu.hook.port = 65533
        bot.config.tz = 'UTC'
        bot.config.zuul = munch.Munch()
        bot.config.zuul.hoist_vault_password = 'XYZ123'
        bot.config.stock = munch.Munch()
        bot.config.stock.apikey = 'demo'
    bot.brain = MockBrain()
    bot.calendars = munch.Munch()
    bot.locks = munch.Munch({
        'brain': DummyLock(),
        'channel_stats': DummyLock(),
        'prior_handlers': DummyLock(),
    })
    bot.date_wrangler = du.DateWrangler()
    bot.dead = DummyEvent()
    bot.clients = munch.Munch()
    pkeys = mock.MagicMock()
    pkeys.hiera.private_key = 'key'
    secrets = munch.munchify({
        'keys': {
            'puppet': {
                'keys': pkeys
            }
        }
    })
    bot.secrets = secrets
    return bot


class MockBrain(object):
    def __init__(self, initial=None):
        self.storage = {}
        if initial:
            self.storage.update(initial)

    def keys(self):
        return list(self.storage.keys())

    def items(self):
        return list(self.storage.items())

    def __setitem__(self, k, v):
        self.storage[k] = v

    def __getitem__(self, k):
        return self.storage[k]

    def sync(self):
        pass
