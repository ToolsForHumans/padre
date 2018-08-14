import mock
from testtools import TestCase

from padre.ansible_utils import PlaybookRun

FAKE_ANSIBLE_PATH = "ansible-playbook"
FAKE_ANSIBLE_PLAY = "fake.yaml"


class PlaybookRunTest(TestCase):
    def test_playbookrun_init(self):
        PlaybookRun()

    @mock.patch("padre.utils.find_executable")
    def test_playbookrun_set_get_extras_init(self, mock_find):
        tmp = PlaybookRun(extra_vars={'a': 'b'})
        self.assertEqual("b", tmp.get_extra_var("a"))
        mock_find.return_value = FAKE_ANSIBLE_PATH
        cmd = tmp.form_command(FAKE_ANSIBLE_PLAY)
        mock_find.assert_called_with(FAKE_ANSIBLE_PATH)
        self.assertEqual(
            [FAKE_ANSIBLE_PATH, '--extra-vars', 'a=b', FAKE_ANSIBLE_PLAY],
            cmd)

    @mock.patch("padre.utils.find_executable")
    def test_playbookrun_set_get_extras(self, mock_find):
        tmp = PlaybookRun()
        tmp.set_extra_var("a", "b")
        self.assertEqual("b", tmp.get_extra_var("a"))
        mock_find.return_value = FAKE_ANSIBLE_PATH
        cmd = tmp.form_command(FAKE_ANSIBLE_PLAY)
        mock_find.assert_called_with(FAKE_ANSIBLE_PATH)
        self.assertEqual(
            [FAKE_ANSIBLE_PATH, '--extra-vars', 'a=b', FAKE_ANSIBLE_PLAY],
            cmd)

    @mock.patch("padre.utils.find_executable")
    def test_playbookrun_inventory(self, mock_find):
        tmp = PlaybookRun()
        tmp.inventory = "blah"
        mock_find.return_value = FAKE_ANSIBLE_PATH
        cmd = tmp.form_command(FAKE_ANSIBLE_PLAY)
        mock_find.assert_called_with(FAKE_ANSIBLE_PATH)
        self.assertEqual(
            [FAKE_ANSIBLE_PATH, '--inventory-file',
             'blah', FAKE_ANSIBLE_PLAY],
            cmd)

    @mock.patch("padre.utils.find_executable")
    def test_playbookrun_inventory_init(self, mock_find):
        tmp = PlaybookRun(inventory='blah')
        mock_find.return_value = FAKE_ANSIBLE_PATH
        cmd = tmp.form_command(FAKE_ANSIBLE_PLAY)
        mock_find.assert_called_with(FAKE_ANSIBLE_PATH)
        self.assertEqual(
            [FAKE_ANSIBLE_PATH, '--inventory-file',
             'blah', FAKE_ANSIBLE_PLAY],
            cmd)

    @mock.patch("padre.utils.find_executable")
    def test_playbookrun_start_at_init(self, mock_find):
        tmp = PlaybookRun(start_at='blah')
        mock_find.return_value = FAKE_ANSIBLE_PATH
        cmd = tmp.form_command(FAKE_ANSIBLE_PLAY)
        mock_find.assert_called_with(FAKE_ANSIBLE_PATH)
        self.assertEqual(
            [FAKE_ANSIBLE_PATH, '--start-at-task',
             'blah', FAKE_ANSIBLE_PLAY],
            cmd)

    @mock.patch("padre.utils.find_executable")
    def test_playbookrun_start_at(self, mock_find):
        tmp = PlaybookRun()
        tmp.start_at = "blah"
        mock_find.return_value = FAKE_ANSIBLE_PATH
        cmd = tmp.form_command(FAKE_ANSIBLE_PLAY)
        mock_find.assert_called_with(FAKE_ANSIBLE_PATH)
        self.assertEqual(
            [FAKE_ANSIBLE_PATH, '--start-at-task',
             'blah', FAKE_ANSIBLE_PLAY],
            cmd)

    @mock.patch("padre.utils.find_executable")
    def test_playbookrun_diff(self, mock_find):
        tmp = PlaybookRun()
        tmp.diff = True
        mock_find.return_value = FAKE_ANSIBLE_PATH
        cmd = tmp.form_command(FAKE_ANSIBLE_PLAY)
        mock_find.assert_called_with(FAKE_ANSIBLE_PATH)
        self.assertEqual(
            [FAKE_ANSIBLE_PATH, '--diff', FAKE_ANSIBLE_PLAY],
            cmd)

    @mock.patch("padre.utils.find_executable")
    def test_playbookrun_diff_init(self, mock_find):
        tmp = PlaybookRun(diff=True)
        mock_find.return_value = FAKE_ANSIBLE_PATH
        cmd = tmp.form_command(FAKE_ANSIBLE_PLAY)
        mock_find.assert_called_with(FAKE_ANSIBLE_PATH)
        self.assertEqual(
            [FAKE_ANSIBLE_PATH, '--diff', FAKE_ANSIBLE_PLAY],
            cmd)

    @mock.patch("padre.utils.find_executable")
    def test_playbookrun_verbosity_init(self, mock_find):
        tmp = PlaybookRun(verbosity=1)
        mock_find.return_value = FAKE_ANSIBLE_PATH
        cmd = tmp.form_command(FAKE_ANSIBLE_PLAY)
        mock_find.assert_called_with(FAKE_ANSIBLE_PATH)
        self.assertEqual(
            [FAKE_ANSIBLE_PATH, '-v', FAKE_ANSIBLE_PLAY],
            cmd)

    @mock.patch("padre.utils.find_executable")
    def test_playbookrun_user_init(self, mock_find):
        tmp = PlaybookRun(remote_user='bob')
        mock_find.return_value = FAKE_ANSIBLE_PATH
        cmd = tmp.form_command(FAKE_ANSIBLE_PLAY)
        mock_find.assert_called_with(FAKE_ANSIBLE_PATH)
        self.assertEqual(
            [FAKE_ANSIBLE_PATH, '--user', 'bob', FAKE_ANSIBLE_PLAY],
            cmd)

    @mock.patch("padre.utils.find_executable")
    def test_playbookrun_user(self, mock_find):
        tmp = PlaybookRun()
        tmp.remote_user = "bob"
        mock_find.return_value = FAKE_ANSIBLE_PATH
        cmd = tmp.form_command(FAKE_ANSIBLE_PLAY)
        mock_find.assert_called_with(FAKE_ANSIBLE_PATH)
        self.assertEqual(
            [FAKE_ANSIBLE_PATH, '--user', 'bob', FAKE_ANSIBLE_PLAY],
            cmd)

    @mock.patch("padre.utils.find_executable")
    def test_playbookrun_check(self, mock_find):
        tmp = PlaybookRun()
        tmp.check = True
        mock_find.return_value = FAKE_ANSIBLE_PATH
        cmd = tmp.form_command(FAKE_ANSIBLE_PLAY)
        mock_find.assert_called_with(FAKE_ANSIBLE_PATH)
        self.assertEqual(
            [FAKE_ANSIBLE_PATH, '--check', FAKE_ANSIBLE_PLAY],
            cmd)

    @mock.patch("padre.utils.find_executable")
    def test_playbookrun_check_init(self, mock_find):
        tmp = PlaybookRun(check=True)
        mock_find.return_value = FAKE_ANSIBLE_PATH
        cmd = tmp.form_command(FAKE_ANSIBLE_PLAY)
        mock_find.assert_called_with(FAKE_ANSIBLE_PATH)
        self.assertEqual(
            [FAKE_ANSIBLE_PATH, '--check', FAKE_ANSIBLE_PLAY],
            cmd)

    @mock.patch("padre.utils.find_executable")
    def test_playbookrun_limit_init(self, mock_find):
        tmp = PlaybookRun(limit='bbb')
        mock_find.return_value = FAKE_ANSIBLE_PATH
        cmd = tmp.form_command(FAKE_ANSIBLE_PLAY)
        mock_find.assert_called_with(FAKE_ANSIBLE_PATH)
        self.assertEqual(
            [FAKE_ANSIBLE_PATH, '--limit', "bbb", FAKE_ANSIBLE_PLAY],
            cmd)

    @mock.patch("padre.utils.find_executable")
    def test_playbookrun_limit(self, mock_find):
        tmp = PlaybookRun()
        tmp.limit = "bbb"
        mock_find.return_value = FAKE_ANSIBLE_PATH
        cmd = tmp.form_command(FAKE_ANSIBLE_PLAY)
        mock_find.assert_called_with(FAKE_ANSIBLE_PATH)
        self.assertEqual(
            [FAKE_ANSIBLE_PATH, '--limit', "bbb", FAKE_ANSIBLE_PLAY],
            cmd)

    @mock.patch("padre.utils.find_executable")
    def test_playbookrun_step_init(self, mock_find):
        tmp = PlaybookRun(step=True)
        mock_find.return_value = FAKE_ANSIBLE_PATH
        cmd = tmp.form_command(FAKE_ANSIBLE_PLAY)
        mock_find.assert_called_with(FAKE_ANSIBLE_PATH)
        self.assertEqual(
            [FAKE_ANSIBLE_PATH, '--step', FAKE_ANSIBLE_PLAY],
            cmd)

    @mock.patch("padre.utils.find_executable")
    def test_playbookrun_step(self, mock_find):
        tmp = PlaybookRun()
        tmp.step = True
        mock_find.return_value = FAKE_ANSIBLE_PATH
        cmd = tmp.form_command(FAKE_ANSIBLE_PLAY)
        mock_find.assert_called_with(FAKE_ANSIBLE_PATH)
        self.assertEqual(
            [FAKE_ANSIBLE_PATH, '--step', FAKE_ANSIBLE_PLAY],
            cmd)
