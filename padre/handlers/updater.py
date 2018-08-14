# -*- coding: utf-8 -*-

import functools
import logging
import pkg_resources

from padre import authorizers as auth
from padre import channel as c
from padre import exceptions as excp
from padre import followers
from padre import handler
from padre import matchers
from padre import trigger
from padre import updater_utils as uu

LOG = logging.getLogger(__name__)


class Handler(handler.TriggeredHandler):
    """Triggers a workflow to downgrade/upgrade the version of this bot."""
    wait_jenkins_queue_item = 0.1
    config_section = 'updater'
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('upgrade', takes_args=True),
            trigger.Trigger('update', takes_args=True),
            trigger.Trigger('upgrayedd', takes_args=True),
        ],
        'authorizer': auth.user_in_ldap_groups('admins_cloud'),
        'args': {
            'order': [
                'version',
            ],
            'help': {
                'version': ('version of padre container to deploy'
                            ' (must exist in artifactory), if'
                            ' not provided then the lastest will'
                            ' be found'),
            },
        }
    }
    required_clients = ('jenkins',)
    required_secrets = (
        'ci.artifactory.ro_account',
    )

    def _await_confirm(self, old_version, version, changelog_lines):
        def _show_others_active():
            active_handlers = len(self.bot.active_handlers)
            return ("There are %s other active"
                    # Remove one since thats the upgrade handler itself...
                    " handlers.") % (max(0, active_handlers - 1))
        pretext_lines = [
            "Newer version `%s` found!" % version,
            "I am older version `%s`." % old_version,
        ]
        text_lines = []
        if changelog_lines:
            text_lines.append("Last `%s` changes:" % len(changelog_lines))
            text_lines.extend(changelog_lines)
        attachments = [{
            'pretext': "\n".join(pretext_lines),
            'mrkdwn_in': ['pretext', 'text'],
            "text": "\n".join(text_lines),
        }]
        self.message.reply_attachments(
            text="Good %s." % self.date_wrangler.get_when(),
            attachments=attachments,
            link_names=True, as_user=True,
            channel=self.message.body.channel,
            log=LOG, thread_ts=self.message.body.get("ts"))
        replier = functools.partial(self.message.reply_text,
                                    threaded=True, prefixed=False,
                                    thread_ts=self.message.body.ts)
        f = followers.ConfirmMe(confirms_what='upgrading',
                                confirm_self_ok=True,
                                check_func=_show_others_active)
        replier(f.generate_who_satisifies_message(self))
        self.wait_for_transition(follower=f, wait_timeout=300,
                                 wait_start_state='CONFIRMING')
        if self.state == 'CONFIRMED_CANCELLED':
            raise excp.Cancelled

    def _run(self, **kwargs):
        replier = functools.partial(self.message.reply_text,
                                    threaded=True, prefixed=False)
        me = pkg_resources.get_distribution('padre')
        ro_account = self.bot.secrets.ci.artifactory.ro_account
        version = kwargs.get("version")
        version_provided = bool(version)
        project_url = self.bot.config.updater.project_url
        path = None
        if not version_provided:
            replier("Scanning artifactory, please wait...")
            newer_paths_it = uu.iter_updates(me.version,
                                             ro_account, project_url)
            newer_paths = sorted(newer_paths_it, key=lambda v: v.version)
            if newer_paths:
                path = newer_paths[-1].path
                version = str(newer_paths[-1].version)
        if not version:
            replier("No potentially upgradeable versions"
                    " found under '%s'" % project_url)
            return
        if me.version == version:
            replier("Nothing to upgrade, version desired is equivalent"
                    " to active version.")
            return
        if path is None:
            tmp_path = uu.check_fetch_version(version, ro_account, project_url)
            path = tmp_path.path
        self._await_confirm(
            me.version, version, uu.extract_changelog(path))
        self.change_state("UPGRADING")
        jenkins_job = self.config.jenkins_job
        jenkins_client = self.bot.clients.jenkins_client
        job = jenkins_client.get_job(jenkins_job)
        if job is not None:
            replier(
                "Triggering upgrade to"
                " version `%s` by kicking job `%s`." % (version,
                                                        jenkins_job))
            qi = job.invoke(build_params={
                'image_tag': version,
                'bot': self.bot.name or "",
            })
            replier("Your upgrade to `%s` job"
                    " has been queued." % version)
            build = None
            while build is None:
                if self.dead.is_set():
                    # Oh well, someone else killed us...
                    raise excp.Dying
                qi.poll()
                build = qi.get_build()
                if build is None:
                    self.dead.wait(self.wait_jenkins_queue_item)
            replier(
                "Your upgrade to `%s` job has"
                " started at %s. I am going into stealth/quiet"
                " mode until then (resurrection expected in %0.2f"
                " seconds), goodbye..." % (version, build.url,
                                           build.get_eta()))
            self.bot.quiescing = True
            self.bot.scheduler.shutdown(wait=False)
        else:
            raise excp.NotFound(
                "Jenkins upgrade job '%s' was not"
                " found" % jenkins_job)
