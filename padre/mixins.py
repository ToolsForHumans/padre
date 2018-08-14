# -*- coding: utf-8 -*-

from __future__ import absolute_import

import hashlib
import logging
import os
import threading

import github
from oslo_utils import timeutils
from oslo_utils import units

from padre import ansible_utils as au
from padre import template_utils as tu
from padre import utils

LOG = logging.getLogger(__name__)


class TemplateUser(object):
    def template_exists(self, template_name):
        try:
            template_path = tu.find_template(
                self.template_dirs, template_name,
                template_subdir=self.template_subdir)
        except tu.MissingTemplate:
            return False
        else:
            return bool(template_path)

    def render_template(self, template_name, template_params, **kwargs):
        kwargs['template_subdir'] = self.template_subdir
        return tu.render_template(self.template_dirs, template_name,
                                  template_params, **kwargs)


class AnsibleRunner(object):
    """Mixin to some handler to add ansible running/capturing capabilities."""

    report_period = 10.0
    gist_update_period = 10.0

    def _run_runner_run(self, tmp_dir, replier, runner, playbook,
                        success_msg, fail_msg, run_kwargs=None,
                        pbar=None, max_gist_mb=None):

        def update_or_create_gist(gists, gist_mapping,
                                  stdout_path, stderr_path):
            to_send = {}
            to_send_hashes = {}
            for key, path in [('stderr', stderr_path),
                              ('stdout', stdout_path)]:
                with open(path, 'rb') as fh:
                    if max_gist_mb is None:
                        contents = fh.read()
                    else:
                        if max_gist_mb <= 0:
                            contents = ''
                        else:
                            contents = utils.read_backwards_up_to_chop(
                                fh, units.Mi * max_gist_mb)
                    contents = contents.strip()
                    if contents:
                        name = gist_mapping[key]
                        to_send[name] = github.InputFileContent(contents)
                        hasher = hashlib.new("md5")
                        hasher.update(contents)
                        to_send_hashes[key] = hasher.hexdigest()
            if gists and to_send:
                _gist, gist_hashes = gists[0]
                if gist_hashes == to_send_hashes:
                    # Don't bother sending anything if nothing has changed...
                    to_send.clear()
            if to_send:
                just_made = False
                try:
                    if gists:
                        gist, gist_hashes = gists[0]
                        gist.edit(files=to_send)
                        gist_hashes.update(to_send_hashes)
                    else:
                        just_made = True
                        me = self.bot.clients.github_client.get_user()
                        gist = me.create_gist(True, to_send)
                        gists.append((gist, to_send_hashes))
                except Exception:
                    if just_made:
                        LOG.warn("Failed uploading new gist for run of %s",
                                 playbook, exc_info=True)
                    else:
                        LOG.warn("Failed uploading edit of gist"
                                 " for run of %s", playbook, exc_info=True)
                else:
                    if just_made and gists:
                        gist, _gist_hashes = gists[0]
                        replier("Gist url at: %s" % gist.html_url)

        def report_on_it(dead, ara_reports_url,
                         gists, gist_mapping,
                         stdout_path, stderr_path):
            started_at = timeutils.now()
            last_report = timeutils.now()
            last_gist_update = timeutils.now()
            emitted_ara = False
            while not dead.is_set():
                now = timeutils.now()
                secs_since_last_report = now - last_report
                if secs_since_last_report >= self.report_period:
                    if not emitted_ara and ara_reports_url:
                        replier("Progress can be"
                                " watched at: %s" % ara_reports_url)
                        emitted_ara = True
                    if pbar is not None:
                        pbar.update(
                            'Your playbook has been running for'
                            ' %s...' % utils.format_seconds(now - started_at))
                    last_report = now
                secs_since_last_gist_update = now - last_gist_update
                if secs_since_last_gist_update >= self.gist_update_period:
                    update_or_create_gist(gists, gist_mapping,
                                          stdout_path, stderr_path)
                    last_gist_update = now
                dead.wait(min([self.gist_update_period, self.report_period]))

        def maybe_stop_it():
            if self.dead.is_set():
                replier("I have been terminated, please"
                        " re-run this playbook and/or command when"
                        " I am alive again.")
                return au.TimeoutResult.TERM
            if self.state == 'EXECUTING_TERM':
                return au.TimeoutResult.TERM
            if self.state == 'EXECUTING_KILLED':
                return au.TimeoutResult.KILL
            if self.state == 'EXECUTING_INTERRUPT':
                return au.TimeoutResult.INT

        ara_reports_url = None
        if self.config.get("ara_enabled"):
            ara_port = self.config.get("ara_port")
            ara_hostname = self.config.get("ara_hostname")
            if not ara_hostname:
                ara_hostname = self.bot.hostname
            if not ara_port or ara_port == 80:
                ara_reports_url = "http://%s/reports/" % (ara_hostname)
            elif ara_port == 443:
                ara_reports_url = "https://%s/reports/" % (ara_hostname)
            else:
                ara_reports_url = "http://%s:%s/reports/" % (ara_hostname,
                                                             ara_port)

        gist_mapping = {}
        gists = []  # There will only really be one, but ya, python...
        for key in ('stderr', 'stdout'):
            name = os.path.basename(playbook)
            name += "." + key + ".txt"
            gist_mapping[key] = name

        # TODO(harlowja): add interruption and better logging...
        #
        # also put the logs somewhere... (when ara can do this)
        stderr_path = os.path.join(tmp_dir, "stderr")
        stdout_path = os.path.join(tmp_dir, "stdout")
        with open(stderr_path, 'wb') as stderr_fh:
            with open(stdout_path, 'wb') as stdout_fh:
                with open(os.devnull, 'rb') as stdin_fh:
                    watcher_done = threading.Event()
                    watcher = threading.Thread(
                        target=report_on_it, args=(watcher_done,
                                                   ara_reports_url,
                                                   gists, gist_mapping,
                                                   stdout_path, stderr_path))
                    watcher.daemon = True
                    watcher.start()
                    try:
                        if run_kwargs is None:
                            run_kwargs = {}
                        result = runner.run(
                            playbook,
                            on_timeout_callback=maybe_stop_it,
                            stdin=stdin_fh, stdout=stdout_fh,
                            stderr=stderr_fh,
                            **run_kwargs)
                    finally:
                        watcher_done.set()
                        watcher.join()

        if result.was_ok():
            replier(success_msg)
        else:
            replier(fail_msg)

        if ara_reports_url:
            replier("Playbook report(s) at: %s" % ara_reports_url)

        update_or_create_gist(gists, gist_mapping,
                              stdout_path, stderr_path)

        return result
