import mock
from testtools import TestCase

from datetime import datetime

from padre.tests import common
from padre.watchers import gerrit


class GerritEntityTest(TestCase):
    def test_from_data(self):
        data = {
            'email': 'user@example.com', 'name': 'User', 'username': 'username'
        }
        entity = gerrit.extract_entity(data)
        self.assertEqual(entity, {
            'email': 'user@example.com', 'name': 'User', 'username': 'username'
        })


class GerritPatchSetTest(TestCase):
    def test_from_data(self):
        author = {
            'email': 'user@example.com', 'name': 'User', 'username': 'username'
        }
        data = {
            'author': author,
            'createdOn': 1502386349,
            'sizeDeletions': 0,
            'sizeInsertions': 10,
            'kind': 'kind',
            'revision': 'revision',
            'uploader': author
        }
        patchset = gerrit.extract_patch_set(data)
        self.assertEqual(patchset, {
            'author': {'email': 'user@example.com',
                       'name': 'User',
                       'username': 'username'},
            'created_on': datetime.fromtimestamp(1502386349),
            'deletes': 0,
            'inserts': 10,
            'kind': 'kind',
            'revision': 'revision',
            'uploader': {'email': 'user@example.com',
                         'name': 'User',
                         'username': 'username'}
        })


class GerritChangeTest(TestCase):
    def setUp(self):
        super(GerritChangeTest, self).setUp()
        self.data = {
            'branch': 'branch',
            'commit_message': 'commit_message',
            'id': 'id',
            'number': 10,
            'owner': {'email': 'user@example.com',
                      'name': 'User',
                      'username': 'username'},
            'project': 'project',
            'status': 'status',
            'subject': 'subject',
            'topic': 'topic',
            'url': 'url'
        }

        self.author = {
            'email': 'user@example.com', 'name': 'User', 'username': 'username'
        }

        self.fromdata = {
            'branch': 'branch',
            'commitMessage': 'commit_message',
            'id': 'id',
            'number': 10,
            'owner': self.author,
            'project': 'project',
            'status': 'status',
            'subject': 'subject',
            'topic': 'topic',
            'url': 'url'
        }

    def test_from_data(self):
        change = gerrit.extract_change(self.fromdata)
        self.assertEqual(change, self.data)


class GerritPatchsetCreatedTest(TestCase):
    def setUp(self):
        super(GerritPatchsetCreatedTest, self).setUp()
        self.author = {
            'email': 'user@example.com', 'name': 'User', 'username': 'username'
        }

        self.patchset = {
            'author': self.author,
            'created_on': datetime.fromtimestamp(1502386349),
            'deletes': 0,
            'inserts': 10,
            'kind': 'kind',
            'revision': 'revision',
            'uploader': self.author
        }

        self.fromPatchset = {
            'author': self.author,
            'createdOn': 1502386349,
            'sizeDeletions': 0,
            'sizeInsertions': 10,
            'kind': 'kind',
            'revision': 'revision',
            'uploader': self.author
        }

        self.change = {
            'branch': 'branch',
            'commit_message': 'commit_message',
            'id': 'id',
            'number': 10,
            'owner': self.author,
            'project': 'project',
            'status': 'status',
            'subject': 'subject',
            'topic': 'topic',
            'url': 'url'
        }

        self.fromChange = {
            'branch': 'branch',
            'commitMessage': 'commit_message',
            'id': 'id',
            'number': 10,
            'owner': self.author,
            'project': 'project',
            'status': 'status',
            'subject': 'subject',
            'topic': 'topic',
            'url': 'url'
        }

        self.patchsetcreated = {
            'patch_set': self.patchset,
            'change': self.change,
            'uploader': self.author,
            'created_on': datetime.fromtimestamp(1502386349),
        }

        self.fromPatchsetcreated = {
            'patchSet': self.fromPatchset,
            'change': self.fromChange,
            'uploader': self.author,
            'eventCreatedOn': 1502386349,
        }

    def test_from_data(self):
        patchset = gerrit.extract_patch_set_created(self.fromPatchsetcreated)
        self.assertEqual(self.patchsetcreated, patchset)


class GerritWatcher(TestCase):
    def test_watcher(self):
        bot = common.make_bot()
        client = mock.MagicMock()
        bot.clients.gerrit_mqtt_client = client
        watcher = gerrit.Watcher(bot)
        watcher.run()
        client.run.assert_called_once()
