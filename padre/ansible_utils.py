import collections
import copy
import logging

import six

from padre import process_utils as pu
from padre import utils


LOG = logging.getLogger(__name__)
MAX_FORKS = 44
MAX_VERBOSE = 4  # Only seems to go up to -vvvv

TimeoutResult = pu.TimeoutResult


class PlaybookRun(object):
    """Slightly nicer way to interact with `ansible-playbook`."""

    def __init__(self, extra_vars=None, start_at=None,
                 verbosity=None, diff=False, limit=None,
                 forks=None, inventory=None,
                 step=False, check=False, remote_user=None,
                 vault_path=None, tags=None,
                 ssh_common_args=None):
        if extra_vars is None:
            extra_vars = collections.OrderedDict()
        self.extra_vars = extra_vars
        self.start_at = start_at
        self.verbosity = verbosity
        self.diff = diff
        self.limit = limit
        self.forks = forks
        self.inventory = inventory
        self.step = step
        self.check = check
        self.remote_user = remote_user
        self.vault_path = vault_path
        self.tags = tags
        self.ssh_common_args = ssh_common_args

    def _fetch_args(self):
        args = collections.OrderedDict()
        if self.extra_vars:
            args['extra-vars'] = self.extra_vars.copy()
        if self.start_at is not None:
            args['start-at-task'] = self.start_at
        if self.verbosity is not None:
            args['verbose'] = self.verbosity
        else:
            args['verbose'] = 0
        args['diff'] = self.diff
        if self.limit:
            args['limit'] = self.limit
        if self.forks is not None:
            args['forks'] = self.forks
        if self.inventory is not None:
            args['inventory-file'] = self.inventory
        args['step'] = self.step
        args['check'] = self.check
        if self.remote_user:
            args['user'] = self.remote_user
        if self.vault_path is not None:
            args['vault-password-file'] = self.vault_path
        if self.tags:  # None or '' would both result in invalid tags
            args['tags'] = self.tags
        if self.ssh_common_args:
            args['ssh-common-args'] = self.ssh_common_args
        return args

    def set_extra_var(self, var, val):
        self.extra_vars[var] = val

    def get_extra_var(self, var, default=None):
        return self.extra_vars.get(var, default)

    def form_command(self, playbook, printable=False):
        ansible_playbook_bin = utils.find_executable("ansible-playbook")
        if not ansible_playbook_bin:
            raise RuntimeError("No ansible-playbook command found")
        cmd = [ansible_playbook_bin]
        args = self._fetch_args()
        if printable:
            args = self._strip_secrets(args)
        for arg_name, val in six.iteritems(args):
            if arg_name == 'verbose':
                val = min(MAX_VERBOSE, int(val))
                if val > 0:
                    cmd.append("-%s" % ("v" * val))
            elif arg_name == 'extra-vars':
                tmp_arg_name = "--" + arg_name
                for k, v in six.iteritems(val):
                    cmd.append(tmp_arg_name)
                    cmd.append("%s=%s" % (k, v))
            elif arg_name == 'forks':
                val = min(MAX_FORKS, int(val))
                if val >= 0:
                    cmd.append("--" + arg_name)
                    cmd.append(str(val))
            elif arg_name in ['check', 'step', 'diff']:
                if val:
                    cmd.append("--" + arg_name)
            else:
                cmd.append("--" + arg_name)
                if val is not None:
                    # This just makes this one easier to read by humans...
                    if printable and arg_name == 'ssh-common-args':
                        cmd.append("'" + str(val) + "'")
                    else:
                        cmd.append(str(val))
        cmd.append(playbook)
        return cmd

    def _strip_secrets(self, args):
        secrets = ['username', 'password', 'token']
        clean_args = copy.deepcopy(args)
        for arg, val in six.iteritems(clean_args):
            if arg in secrets:
                clean_args[arg] = '*****'
            if arg == 'extra-vars':
                for k, v in six.iteritems(val):
                    if k in secrets:
                        clean_args[arg][k] = '*****'
        return clean_args

    def run(self, playbook, timeout=0.1, on_timeout_callback=None, **kwargs):
        cmd = self.form_command(playbook)
        kwargs.setdefault('close_fds', True)
        return pu.run(cmd, timeout=timeout,
                      on_timeout_callback=on_timeout_callback, **kwargs)
