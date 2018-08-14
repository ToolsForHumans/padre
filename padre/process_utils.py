import logging
import signal

import enum
import six
import subprocess32

PIPE = subprocess32.PIPE
LOG = logging.getLogger(__name__)


class ProcessExecutionError(Exception):
    """Borrowed from cloud-init (which borrowed it from somewhere else)."""

    MESSAGE_TMPL = ('%(description)s\n'
                    'Command: %(command)s\n'
                    'Exit code: %(exit_code)s\n'
                    'Reason: %(reason)s\n'
                    'Stdout: %(stdout)s\n'
                    'Stderr: %(stderr)s')
    EMPTY_ATTR = '-'

    def __init__(self, stdout=None, stderr=None,
                 exit_code=None, command=None,
                 description=None, reason=None,
                 errno=None):
        if not command:
            self.command = self.EMPTY_ATTR
        else:
            self.command = command

        if not description:
            self.description = 'Unexpected error while running command.'
        else:
            self.description = description

        if not isinstance(exit_code, six.integer_types):
            self.exit_code = self.EMPTY_ATTR
        else:
            self.exit_code = exit_code

        if not stderr:
            self.stderr = self.EMPTY_ATTR
        else:
            self.stderr = stderr

        if not stdout:
            self.stdout = self.EMPTY_ATTR
        else:
            self.stdout = stdout

        if reason:
            self.reason = reason
        else:
            self.reason = self.EMPTY_ATTR

        self.errno = errno
        message = self.MESSAGE_TMPL % {
            'description': self.description,
            'command': self.command,
            'exit_code': self.exit_code,
            'stdout': self.stdout,
            'stderr': self.stderr,
            'reason': self.reason,
        }
        super(ProcessExecutionError, self).__init__(message)


class TimeoutResult(enum.Enum):
    KILL = signal.SIGKILL
    TERM = signal.SIGTERM
    INT = signal.SIGINT


class Result(object):
    def __init__(self, command, exit_code=0, stderr='', stdout=''):
        self.command = command
        self.exit_code = exit_code
        self.stderr = stderr
        self.stdout = stdout

    def was_ok(self, good_exits=(0,)):
        if self.exit_code in good_exits:
            return True
        else:
            return False

    def raise_for_status(self, good_exits=(0,)):
        if not self.was_ok(good_exits=good_exits):
            raise ProcessExecutionError(stdout=self.stdout,
                                        stderr=self.stderr,
                                        command=self.command,
                                        exit_code=self.exit_code)


def run(command, timeout=0.1,
        on_timeout_callback=None, env=None, cwd=None,
        close_fds=None, stderr=None, stdout=None, stdin=None):
    return _run(command, timeout=timeout,
                on_timeout_callback=on_timeout_callback,
                env=env, cwd=cwd, close_fds=close_fds,
                stderr=stderr, stdout=stdout, stdin=stdin)


def _run(command, timeout=0.1, on_timeout_callback=None, **kwargs):
    if not command:
        raise ValueError("Command to run must not be empty")
    cmd = []
    for cmd_piece in command:
        if not isinstance(cmd_piece, six.string_types):
            cmd.append(str(cmd_piece))
        else:
            cmd.append(cmd_piece)
    if kwargs.get("stdout") == PIPE or kwargs.get("stderr") == PIPE:
        use_communicate = True
    else:
        use_communicate = False
    stdout_buf = six.BytesIO()
    stderr_buf = six.BytesIO()
    with subprocess32.Popen(cmd, **kwargs) as sp:
        while sp.returncode is None:
            try:
                if use_communicate:
                    stdout, stderr = sp.communicate(timeout=timeout)
                    stderr_buf.write(stderr)
                    stdout_buf.write(stdout)
                else:
                    sp.wait(timeout=timeout)
            except subprocess32.TimeoutExpired:
                if on_timeout_callback is not None:
                    r = on_timeout_callback()
                    if r is not None:
                        sig = r.value
                        LOG.debug("Sending signal %s(%s) to %s",
                                  r.name, sig, sp.pid)
                        sp.send_signal(sig)
        return Result(cmd, exit_code=sp.returncode,
                      stdout=stdout_buf.getvalue(),
                      stderr=stderr_buf.getvalue())
