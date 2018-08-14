# -*- coding: utf-8 -*-

from __future__ import absolute_import

import collections
import functools
import json
import logging
import random

from apscheduler.triggers import cron
from oslo_utils import reflection
from oslo_utils import timeutils
import six
from six.moves import range as compat_range
import tinyjenkins as tj

from voluptuous import All
from voluptuous import Length
from voluptuous import Required
from voluptuous import Schema

from padre import authorizers as auth
from padre import channel as c
from padre import exceptions as excp
from padre import followers
from padre import handler
from padre import handler_utils as hu
from padre import matchers
from padre import periodic_utils as peu
from padre import schema_utils as scu
from padre import slack_utils as su
from padre import trigger
from padre import utils

LOG = logging.getLogger(__name__)
CONSOLE_LINES = 20


def _expand_params(parameters):
    for params in parameters:
        tmp_params = {}
        for k, v in six.iteritems(params):
            if isinstance(v, (list, tuple)):
                # Jenkins doesn't understand our list format, so send
                # all lists as comma separated values instead...
                v = ", ".join(v)
            tmp_params[k] = v
        yield tmp_params


def _format_build_console(console_out, line_limit=-1, add_header=True):
    console_out_nice = []
    lines_in_console = console_out.count("\n") + 1
    if line_limit >= 0 and lines_in_console > line_limit:
        console_out_pieces = console_out.split("\n")
        if add_header:
            console_out_nice.append(
                "Last %s console lines:" % line_limit)
        console_out_nice.append("```")
        console_out_nice.extend(console_out_pieces[-line_limit:])
    else:
        if add_header:
            console_out_nice.append(
                "Full console (%s lines):" % lines_in_console)
        console_out_nice.append("```")
        console_out_nice.append(console_out)
    console_out_nice.append("```")
    return "\n".join(console_out_nice)


def _console_get_result_dict(console_out):
    token = 'Howdy pardner, I heard you wanted some results: '
    for line in console_out.split('\n'):
        if line.startswith(token):
            return json.loads(line[len(token):])


def _format_result_dict(result_dict, add_header=True):
    result_dict_nice = []
    if add_header:
        result_dict_nice.append("You got results!")
    result_dict_nice.append("```")
    result_dict_nice.append(utils.prettify_yaml(
        result_dict, explicit_start=False, explicit_end=False))
    result_dict_nice.append("```")
    return "\n".join(result_dict_nice)


class JobWatcher(handler.TriggeredHandler):
    # Check if we are dead every this many seconds.
    poll_delay = 0.1

    def __init__(self, bot, message):
        super(JobWatcher, self).__init__(bot, message)
        self.build = None
        self.job = None

    def _watch(self, job_name, build, jenkins_client, job=None):
        replier = self.message.reply_text
        replier = functools.partial(replier, threaded=True, prefixed=False)

        if job is None:
            replier("Locating job `%s`, please wait..." % job_name)
            job = jenkins_client.get_job(job_name)
            if job is None:
                replier("Job `%s` was not found!" % job_name)
                return

        if isinstance(build, six.string_types):
            build = int(build)
        if isinstance(build, six.integer_types):
            build_num = build
            replier("Locating build `%s`, please wait..." % build_num)
            build = job.get_build(build)
            if build is None:
                replier("Job `%s` build `%s` was"
                        " not found!" % (job_name, build_num))
                return

        build_num = build.number
        replier("Watching initiated for"
                " job `%s` build `%s`" % (job_name, build_num))

        max_build_wait = None
        try:
            max_build_wait = self.config.jenkins.max_build_wait
        except AttributeError:
            pass

        report_bar = self.message.make_manual_progress_bar()
        with timeutils.StopWatch(duration=max_build_wait) as watch:
            # At this point we can be cancelled safely, so allow that
            # to happen (or at least allow someone to try it).
            self.job = job
            self.build = build
            if build.is_running():
                still_running = True
                build_eta = build.get_eta()
                if build_eta != float("inf"):
                    eta_sec = max(0, build_eta - watch.elapsed())
                    eta_text = "%0.2fs/%0.2fm" % (eta_sec, eta_sec / 60.0)
                    report_bar.update(
                        "Estimated time to completion is %s" % eta_text)
                else:
                    report_bar.update("Estimated time to"
                                      " completion is unknown.")
                last_build_fetch = timeutils.now()
                while still_running:
                    if watch.expired():
                        replier("Timed out (waited %0.2f seconds) while"
                                " checking your build." % watch.elapsed())
                        return
                    self.dead.wait(self.poll_delay)
                    if self.dead.is_set():
                        replier("I have been terminated, please"
                                " check the jenkins job url for the"
                                " final result.")
                        return
                    now = timeutils.now()
                    since_last_build_info = now - last_build_fetch
                    if since_last_build_info > self.build_info_delay:
                        build.poll()
                        if build.is_running():
                            build_eta = build.get_eta()
                            if build_eta != float("inf"):
                                eta_sec = build_eta - watch.elapsed()
                                eta_sec_min = eta_sec / 60.0
                                if eta_sec >= 0:
                                    eta_text = "%0.2fs/%0.2fm" % (eta_sec,
                                                                  eta_sec_min)
                                    report_bar.update(
                                        "Estimated time to"
                                        " completion is %s" % eta_text)
                                else:
                                    eta_sec = eta_sec * -1
                                    eta_sec_min = eta_sec_min * -1
                                    eta_text = "%0.2fs/%0.2fm" % (eta_sec,
                                                                  eta_sec_min)
                                    report_bar.update(
                                        "Job is %s over estimated time"
                                        " to completion" % eta_text)
                            else:
                                report_bar.update("Estimated time to"
                                                  " completion is unknown.")
                        else:
                            still_running = False
                        since_last_build_info = now

        # Force getting the newest data...
        build.poll()
        result = build.get_result()

        # Try to get some console log (if this fails it doesn't really matter)
        result_dict = None
        console_out_pretty = None
        try:
            console_out = build.get_console()
            console_out_pretty = _format_build_console(
                console_out, line_limit=CONSOLE_LINES)
            result_dict = _console_get_result_dict(console_out)
        except Exception:
            LOG.warn("Failed getting build console for '%s'", build,
                     exc_info=True)

        if not result:
            result = "UNKNOWN"
        replier("Your jenkins job finished with result `%s`" % result)
        if result_dict:
            replier(_format_result_dict(result_dict))

        if result == "FAILURE" and console_out_pretty:
            replier(console_out_pretty)

        return result_dict


class AbortFollower(object):
    @followers.ensure_handles
    def __call__(self, handler, message):
        message_text = utils.canonicalize_text(message.body.text)
        if message_text in ['stop', 'abort', 'cancel']:
            if handler.build is None or handler.job is None:
                return False
            replier = functools.partial(message.reply_text,
                                        threaded=True, prefixed=False,
                                        thread_ts=handler.message.body.ts)
            replier("Build %s is being requested"
                    " to stop." % handler.build.number)
            was_stopped = handler.build.stop(before_poll=True)
            if was_stopped:
                replier("Build %s has been"
                        " stopped." % handler.build.number)
            else:
                replier("Build %s has *not* been"
                        " stopped (is it still"
                        " running?)" % handler.build.number)
            return True
        return False


class ConsoleFollower(object):
    @followers.ensure_handles
    def __call__(self, handler, message):
        message_text = utils.canonicalize_text(message.body.text)
        if message_text == 'console':
            if handler.build is None or handler.job is None:
                return False
            console_out = handler.build.get_console()
            console_out = _format_build_console(
                console_out, line_limit=CONSOLE_LINES,
                add_header=False)
            replier = functools.partial(message.reply_text,
                                        threaded=True, prefixed=False,
                                        thread_ts=handler.message.body.ts)
            replier(console_out)
            return True
        return False


class ConsoleHandler(handler.TriggeredHandler):
    """Gets a jenkins jobs console log."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('jenkins console', takes_args=True),
        ],
        'args': {
            'order': [
                'job_name',
                'build',
                'lines',
            ],
            'schema': Schema({
                Required("job_name"): All(scu.string_types(), Length(min=1)),
                Required("build"): int,
                Required("lines"): int,
            }),
            'converters': {
                'build': int,
                'lines': int,
            },
            'defaults': {
                'lines': CONSOLE_LINES,
            },
            'help': {
                'job_name': "job name to fetch",
                "build": "build identifier to fetch",
                "lines": ("maximum number of lines from the"
                          " console to respond"
                          " with (negative for no limit)"),
            },
        },
        'authorizer': auth.user_in_ldap_groups('admins_cloud'),
    }
    required_clients = ('jenkins',)

    def _run(self, job_name, build, lines):
        replier = self.message.reply_text
        replier = functools.partial(replier, threaded=True, prefixed=False)
        replier("Fetching job `%s` build `%s`"
                " console, please wait..." % (job_name, build))
        clients = self.bot.clients
        job = clients.jenkins_client.get_job(job_name)
        if job is None:
            replier("Job `%s` was not found!" % job_name)
            return
        build_num = build
        build = job.get_build(build_num)
        if build is not None:
            console_out = build.get_console()
            console_out = _format_build_console(console_out, line_limit=lines)
            replier(console_out)
        else:
            replier("Job `%s` build `%s` was"
                    " not found!" % (job_name, build_num))


class WatchHandler(JobWatcher):
    """Watches a jenkins jobs build."""

    build_info_delay = 10

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'followers': [
            ConsoleFollower,
            AbortFollower,
        ],
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('jenkins watch', takes_args=True),
        ],
        'args': {
            'order': [
                'job_name',
                'build',
            ],
            'schema': Schema({
                Required("job_name"): All(scu.string_types(), Length(min=1)),
                Required("build"): int,
            }),
            'converters': {
                'build': int,
            },
            'help': {
                'job_name': "job name to watch",
                "build": "build number to watch",
            },
        },
        'authorizer': auth.user_in_ldap_groups('admins_cloud'),
    }
    required_clients = ('jenkins',)

    def _run(self, job_name, build):
        clients = self.bot.clients
        return self._watch(job_name, build, clients.jenkins_client)


class JobHandler(JobWatcher):
    """Runs a jenkins job (and then watches its build)."""

    job_name = None
    started_messages = tuple([
        "Getting that started for you.",
        "I am on it!",
        "Let me begin."
    ])
    required_clients = ('jenkins',)

    # This needs to be kept low since it appears things jump off
    # the queue and then you lose them into space/thin-air...
    queued_build_info_delay = 0.1

    build_info_delay = 10

    @classmethod
    def insert_periodics(cls, bot, scheduler):
        try:
            jenkins_jobs = bot.config.jenkins.jobs
        except AttributeError:
            jenkins_jobs = {}
        try:
            if cls.job_name:
                job_config = jenkins_jobs[cls.job_name]
            else:
                job_config = {}
        except KeyError:
            job_config = {}
        slack_client = bot.clients.get("slack_client")
        slack_sender = bot.slack_sender
        if slack_client is not None and slack_sender is not None:
            for periodic in job_config.get("periodics", []):
                channel = bot.config.get('periodic_channel')
                if not channel:
                    channel = bot.config.admin_channel
                for periodic_params in _expand_params(periodic['parameters']):
                    jr = peu.make_periodic_runner(
                        "jenkins job targeting job `%s`" % cls.job_name,
                        cls, periodic['period'], channel=channel,
                        log=LOG, args=periodic_params)
                    jr.__module__ = __name__
                    jr.__name__ = "run_jenkins_job"
                    jr_trigger = cron.CronTrigger.from_crontab(
                        periodic['period'], timezone=bot.config.tz)
                    jr_name = reflection.get_callable_name(jr)
                    jr_description = "\n".join([
                        ("Periodic jenkins job"
                         " targeting job '%s'" % cls.job_name),
                        "",
                        "With parameters:",
                        utils.prettify_yaml(
                            periodic_params, explicit_end=False,
                            explicit_start=False),
                    ])
                    scheduler.add_job(
                        jr, trigger=jr_trigger,
                        jobstore='memory',
                        name="\n".join([jr_name, jr_description]),
                        id=utils.hash_pieces([periodic['period'],
                                              jr_name,
                                              jr_description], max_len=8),
                        args=(bot, slack_client, slack_sender),
                        coalesce=True)

    def _run(self, **kwargs):
        jenkins_client = self.bot.clients.jenkins_client
        replier = self.message.reply_text
        replier = functools.partial(replier, threaded=True, prefixed=False)
        max_build_wait = None
        try:
            max_build_wait = self.config.jenkins.max_build_wait
        except AttributeError:
            pass

        # And begin!
        replier(random.choice(self.started_messages))

        job = jenkins_client.get_job(self.job_name)
        if job is None:
            replier("Job `%s` was not found!" % self.job_name)
            return

        qi = job.invoke(build_params=kwargs)
        replier("Your build request has been queued.")
        replier("Waiting for your jenkins job to build...")

        build_status = 'OK'
        build = None
        with timeutils.StopWatch(duration=max_build_wait) as watch:
            while (not self.dead.is_set() and build is None and
                   not watch.expired() and build_status == 'OK'):
                build = qi.get_build()
                if build is None:
                    qi.poll()
                    build = qi.get_build()
                if build is None:
                    LOG.debug("Still waiting on '%s', it has not"
                              " started building yet", qi)
                    wait_secs = self.queued_build_info_delay
                    try:
                        secs_leftover = watch.leftover()
                        if secs_leftover < wait_secs:
                            wait_secs = secs_leftover
                    except RuntimeError:
                        pass
                    self.dead.wait(wait_secs)

        if self.dead.is_set():
            if build is not None:
                replier("I have been terminated, but your build %s"
                        " is building, please go to the jenkins ui"
                        " and look for it at %s." % (build.number, build.url))
            else:
                replier("I have been terminated, but your build"
                        " is in the wait queue, please go to the"
                        " jenkins ui and look for it at %s." % (qi.url))
        elif build_status != 'OK' or watch.expired():
            if watch.expired() and build_status == 'OK':
                build_status = 'BUILD_WAITED_TO_LONG'
            replier("I failed waiting on your jobs queue item due"
                    " to `%s`, sorry come again." % build_status)
        else:
            replier("Your jenkins job build number is %s." % build.number)
            replier("Your jenkins job url is: %s" % build.url)
            return self._watch(self.job_name, build,
                               jenkins_client, job=job)


class JenkinsRestartHandler(handler.TriggeredHandler):
    """Triggers the jenkins the bot is connected to, to restart."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('jenkins restart', takes_args=True),
        ],
        'args': {
            'order': [
                'safe',
            ],
            'schema': Schema({
                Required("safe"): bool,
            }),
            'converters': {
                'safe': hu.strict_bool_from_string,
            },
            'help': {
                'safe': "perform a safe restart (letting active jobs finish)",
            },
            'defaults': {
                'safe': True,
            },
        },
        'authorizer': auth.user_in_ldap_groups('admins_cloud'),
    }
    required_clients = ('jenkins',)

    def _run(self, safe):
        jenkins_client = self.bot.clients.jenkins_client
        replier = self.message.reply_text
        replier = functools.partial(replier, threaded=True, prefixed=False)
        if safe:
            replier("Engaging *safe* jenkins restart, please wait...")
        else:
            replier("Engaging *unsafe* (ie forceful)"
                    " jenkins restart, please wait...")
        if jenkins_client.perform_restart(safe=safe):
            replier("Restart acknowledged.")
        else:
            replier("Restart failed.")


class JenkinsCheckHandler(handler.TriggeredHandler):
    """Checks jobs in jenkins and ensures master branches are working."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('jenkins check', takes_args=True),
        ],
    }
    required_clients = ('jenkins',)

    def _run(self):
        jenkins_client = self.bot.clients.jenkins_client
        replier = functools.partial(self.message.reply_text,
                                    threaded=True, prefixed=False)
        replier("Fetching jenkins details, please wait...")
        job_folders = []
        for job in jenkins_client.iter_jobs(expand_folders=False,
                                            yield_folders=True):
            if isinstance(job, tj.JobFolder):
                job_folders.append(job)
        found = 0
        replier_attachments = self.message.reply_attachments
        for job_folder in sorted(job_folders, key=lambda f: f.name.lower()):
            if self.dead.is_set():
                raise excp.Dying
            master_job = jenkins_client.get_job(
                "%s/job/master" % job_folder.name)
            if not master_job:
                continue
            attachment = {
                'pretext': "Job `%s`." % job_folder.name,
                'title': master_job.name,
                'title_link': master_job.url,
                'mrkdwn_in': ['pretext'],
                'fields': [],
            }
            try:
                attachment['color'] = su.COLORS[master_job.color]
            except KeyError:
                attachment['fields'].append({
                    'title': 'Color',
                    'value': master_job.color,
                    'short': True,
                })
            replier_attachments(attachments=[attachment],
                                log=LOG, link_names=True,
                                as_user=True, text=' ',
                                thread_ts=self.message.body.ts,
                                channel=self.message.body.channel,
                                unfurl_links=False)
            found += 1
        if not found:
            replier("No jobs to check found.")
        else:
            replier("%s jobs scanned. Have a nice day!" % found)


class JenkinsJobHealthHandler(handler.TriggeredHandler):
    """Provides job health for the jenkins the bot is connected to."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('jenkins job-health', takes_args=True),
        ],
        'args': {
            'order': [
                'job_name',
            ],
            'help': {
                'job_name': 'job name to fetch (blank for all)',
            },
            'schema': Schema({
                Required("job_name"): scu.string_types(),
            }),
            'defaults': {
                'job_name': '',
            },
        },
    }
    required_clients = ('jenkins',)
    folder_jobs = ['master']

    @classmethod
    def _iter_jobs(cls, jenkins_client, jobs, folders):
        all_jobs = []
        for job in jobs:
            all_jobs.append((job, job.name))
        # These folders are typically our multibranch jobs, and we
        # care about how some job(s) under that are working out; so
        # find those job(s) if we can...
        for f in folders:
            for f_job_name in cls.folder_jobs:
                f_job_full_name = f.name + "/job/" + f_job_name
                f_job_short_name = f.name + "/" + f_job_name
                f_job = jenkins_client.get_job(f_job_full_name)
                if f_job is not None:
                    all_jobs.append((f_job, f_job_short_name))
        for job, job_name in sorted(all_jobs, key=lambda v: v[1].lower()):
            yield job, job_name

    @classmethod
    def insert_periodics(cls, bot, scheduler):
        try:
            health_report_period = bot.config.jenkins.health_report_period
        except AttributeError:
            pass
        else:
            slack_client = bot.clients.get("slack_client")
            slack_sender = bot.slack_sender
            if slack_client is not None and slack_sender is not None:
                hr = peu.make_periodic_runner(
                    "jenkins health report",
                    cls, health_report_period,
                    channel=bot.config.admin_channel,
                    log=LOG)
                hr.__module__ = __name__
                hr.__name__ = "run_check_jenkins_health"
                hr_trigger = cron.CronTrigger.from_crontab(
                    health_report_period, timezone=bot.config.tz)
                hr_name = reflection.get_callable_name(hr)
                hr_description = "Periodically analyzes jenkins job health."
                scheduler.add_job(
                    hr, trigger=hr_trigger,
                    jobstore='memory',
                    name="\n".join([hr_name, hr_description]),
                    id=utils.hash_pieces([health_report_period, hr_name,
                                          hr_description], max_len=8),
                    args=(bot, slack_client, slack_sender),
                    coalesce=True)

    def _run(self, job_name=''):
        jenkins_client = self.bot.clients.jenkins_client
        replier = functools.partial(self.message.reply_text,
                                    threaded=True, prefixed=False)
        replier_attachments = self.message.reply_attachments
        replier("Calculating jenkins job health, please wait...")
        jobs = []
        folders = []
        for thing in jenkins_client.iter_jobs(yield_folders=True,
                                              expand_folders=False):
            if isinstance(thing, tj.JobFolder):
                folders.append(thing)
            else:
                jobs.append(thing)
        job_lines = []
        job_colors = collections.defaultdict(int)
        for job, a_job_name in self._iter_jobs(jenkins_client, jobs, folders):
            if job_name and a_job_name != job_name:
                continue
            job_color = job.color
            if job_color.endswith("_anime"):
                job_color = job_color[:-len('_anime')]
            if job_color in ('notbuilt', 'disabled'):
                continue
            if job_color in ('green', 'blue', 'red', 'yellow'):
                # Slack doesn't seem to have a blue ball, so just
                # switch it...
                if job_color == 'blue':
                    job_color = 'green'
                pretty_job_color = ":%sball:" % job_color
            else:
                pretty_job_color = job_color
            job_colors[job_color] += 1
            job_lines.append(u"• <%s|%s> %s" % (
                job.url, a_job_name, pretty_job_color))
        num_red = job_colors.get('red', 0)
        num_yellow = job_colors.get('yellow', 0)
        num_ok = job_colors.get("green", 0)
        attachment = {
            'pretext': 'Report for `%s`' % jenkins_client.base_url,
            'text': "\n".join(job_lines),
            'mrkdwn_in': ['text', 'pretext'],
        }
        if num_red:
            attachment['color'] = su.COLORS['red']
        if num_yellow and not num_red:
            attachment['color'] = su.COLORS['yellow']
        if not num_yellow and not num_red and num_ok:
            attachment['color'] = su.COLORS['green']
        replier_attachments(attachments=[attachment],
                            log=LOG, link_names=True,
                            as_user=True, text=' ',
                            thread_ts=self.message.body.ts,
                            channel=self.message.body.channel,
                            unfurl_links=True)


class JenkinsInfoHandler(handler.TriggeredHandler):
    """Provides information on the jenkins the bot is connected to."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('jenkins info', takes_args=True),
        ],
        'args': {
            'order': [
                'show_nodes',
                'show_plugins',
                'show_jobs',
            ],
            'schema': Schema({
                Required("show_nodes"): bool,
                Required("show_plugins"): bool,
                Required("show_jobs"): bool,
            }),
            'converters': {
                'show_nodes': hu.strict_bool_from_string,
                'show_plugins': hu.strict_bool_from_string,
                'show_jobs': hu.strict_bool_from_string,
            },
            'help': {
                'show_nodes': "retrieve node information",
                "show_plugins": "retrieve plugin information",
                "show_jobs": "retrieve job information",
            },
            'defaults': {
                'show_nodes': False,
                'show_plugins': False,
                'show_jobs': False,
            },
        },
    }
    required_clients = ('jenkins',)

    @staticmethod
    def _format_plugin(plugin):
        attachment = {
            'title': plugin.long_name,
            'title_link': plugin.url,
            'fields': [
                {
                    'title': 'Short Name',
                    'value': plugin.name,
                    'short': True,
                },
            ],
            'mrkdwn_in': [],
        }
        attachment['fields'].append({
            'title': 'Version',
            'value': str(plugin.version),
            'short': True,
        })
        attachment['fields'].append({
            'title': 'Enabled',
            'value': str(plugin.enabled),
            'short': True,
        })
        attachment['fields'].append({
            'title': 'Active',
            'value': str(plugin.active),
            'short': True,
        })
        return attachment

    @staticmethod
    def _format_job_folder(folder):
        attachment = {
            'title': folder.name,
            'title_link': folder.url,
            'fields': [],
        }
        return attachment

    @staticmethod
    def _format_job(job):
        attachment = {
            'title': job.name,
            'title_link': job.url,
            'fields': [],
        }
        try:
            attachment['color'] = su.COLORS[job.color]
        except KeyError:
            pass
        health_report = job.get_health_report()
        if health_report is not None:
            attachment['fields'].append({
                'title': 'Health',
                'value': health_report.description,
                'short': False,
            })
            attachment['fields'].append({
                'title': 'Health Score',
                'value': str(health_report.score),
                'short': True,
            })
        return attachment

    @staticmethod
    def _format_node(node):
        attachment = {
            'fields': [],
            'mrkdwn_in': ['pretext'],
        }
        if node.master:
            attachment['pretext'] = "Master node"
        else:
            attachment['pretext'] = "Slave node"
        attachment['fields'].append({
            'title': 'Name',
            'value': node.name,
            'short': True,
        })
        attachment['fields'].append({
            'title': 'Dynamic',
            'value': str(node.dynamic),
            'short': True,
        })
        attachment['fields'].append({
            'title': 'Offline',
            'value': str(node.offline),
            'short': True,
        })
        if node.offline and node.offline_cause:
            attachment['fields'].append({
                'title': 'Offline Cause',
                'value': str(node.offline_cause),
                'short': False,
            })
        attachment['fields'].append({
            'title': 'Idle',
            'value': str(node.idle),
            'short': True,
        })
        attachment['fields'].append({
            'title': 'Launch Supported',
            'value': str(node.launch_supported),
            'short': True,
        })
        for monitor_name in sorted(node.monitors.keys()):
            val = node.monitors[monitor_name]
            tmp_monitor_name = monitor_name.replace("_", " ")
            tmp_monitor_name = tmp_monitor_name.title()
            attachment['fields'].append({
                'title': tmp_monitor_name,
                'value': str(val),
                'short': True,
            })
        if node.offline:
            attachment['color'] = su.COLORS.red
        return attachment

    def _run(self, show_nodes, show_plugins, show_jobs):
        jenkins_client = self.bot.clients.jenkins_client
        replier = functools.partial(self.message.reply_text,
                                    threaded=True, prefixed=False)
        replier("Fetching jenkins details, please wait...")
        replier_attachments = self.message.reply_attachments
        jenkins_ver = jenkins_client.get_version()
        if not jenkins_ver:
            jenkins_ver = "??"
        jenkins_sess = jenkins_client.get_session()
        if not jenkins_sess:
            jenkins_sess = "??"
        attachments = [{
            'pretext': ("Connected to"
                        " <%s|jenkins>.") % jenkins_client.base_url,
            'mrkdwn_in': ['pretext'],
            'fields': [
                {
                    'title': "Version",
                    'value': str(jenkins_ver),
                    'short': True,
                },
                {
                    'title': "Session",
                    'value': str(jenkins_sess),
                    'short': True,
                },
                {
                    'title': "Connected As",
                    'value': jenkins_client.username,
                    'short': True,
                },
            ],
        }]
        replier_attachments(attachments=attachments,
                            log=LOG, link_names=True,
                            as_user=True,
                            thread_ts=self.message.body.ts,
                            channel=self.message.body.channel,
                            unfurl_links=False)
        if show_nodes:
            replier("Fetching jenkins node details, please wait...")
            # Always put master node(s?) at the front...
            attachments = []
            tmp_nodes = jenkins_client.get_nodes()
            nodes = []
            nodes.extend(node for node in tmp_nodes if node.master)
            nodes.extend(node for node in tmp_nodes if not node.master)
            for node in nodes:
                attachments.append(self._format_node(node))
            replier_attachments(attachments=attachments,
                                log=LOG, link_names=True,
                                as_user=True,
                                thread_ts=self.message.body.ts,
                                channel=self.message.body.channel,
                                unfurl_links=False)
        if show_plugins:
            replier("Fetching jenkins plugin details, please wait...")
            attachments = []
            for plugin in jenkins_client.get_plugins():
                attachments.append(self._format_plugin(plugin))
            replier_attachments(attachments=attachments,
                                log=LOG, link_names=True,
                                as_user=True,
                                thread_ts=self.message.body.ts,
                                channel=self.message.body.channel,
                                unfurl_links=False)
        if show_jobs:
            replier("Fetching jenkins job details, please wait...")
            jobs = []
            folders = []
            for thing in jenkins_client.iter_jobs(yield_folders=True,
                                                  expand_folders=False):
                if isinstance(thing, tj.JobFolder):
                    folders.append(thing)
                else:
                    jobs.append(thing)
            jobs = sorted(jobs, key=lambda job: job.name)
            attachments = []
            for job in jobs:
                attachments.append(self._format_job(job))
            replier_attachments(attachments=attachments,
                                log=LOG, link_names=True,
                                as_user=True,
                                text="Found %s jenkins jobs." % len(jobs),
                                thread_ts=self.message.body.ts,
                                channel=self.message.body.channel,
                                unfurl_links=False)
            folders = sorted(folders, key=lambda folder: folder.name)
            attachments = []
            for folder in folders:
                attachments.append(self._format_job_folder(folder))
            replier_attachments(
                attachments=attachments,
                log=LOG, link_names=True, as_user=True,
                text="Found %s jenkins jobs folders." % len(folders),
                thread_ts=self.message.body.ts,
                channel=self.message.body.channel,
                unfurl_links=False)


def load_jenkins_handlers(jobs, jenkins_client, executor, log=None):
    if log is None:
        log = LOG
    log.info("Generating up to %s jenkins handlers", len(jobs))
    made_classes = []
    futs = []
    job_names = sorted(jobs.keys())
    if log.isEnabledFor(logging.DEBUG):
        for job_name in job_names:
            log.debug("Making handler class for job '%s'", job_name)
    for job_name in job_names:
        job = jobs[job_name]
        fut = executor.submit(_build_handler_from_jenkins,
                              jenkins_client, job_name,
                              description=job.get("summary", ""),
                              cmd_suffix=job.get("cmd_suffix", ""),
                              cmd_prefix=job.get("cmd_prefix", ""))
        futs.append(fut)
    for job_name, fut in zip(job_names, futs):
        job_type_name, job_cls, job_cls_dct = fut.result()
        if job_cls is None:
            log.warn("Handler class for job '%s' was not built, does"
                     " that job exist in jenkins?", job_name)
        else:
            log.debug(
                "Constructed class '%s' with dict %s", job_type_name,
                job_cls_dct)
            made_classes.append(job_cls)
    return made_classes


def _build_handler_from_jenkins(jenkins_client, job_name,
                                restricted_ldap_groups=None,
                                description=None,
                                cmd_suffix='', cmd_prefix=''):
    job = jenkins_client.get_job(job_name)
    if job is None:
        return None, None, None
    handles_what = {
        'args': {},
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'followers': [
            ConsoleFollower,
            AbortFollower,
        ],
        'authorizer': auth.user_in_ldap_groups('admins_cloud'),
        'channel_matcher': matchers.match_channel(c.TARGETED),
    }
    cleaned_job_name = job_name.replace("-", " ").replace("_", " ")

    trigger_text = cleaned_job_name.lower()
    if cmd_suffix:
        trigger_text += " " + cmd_suffix
    if cmd_prefix:
        trigger_text = cmd_prefix + " " + trigger_text

    raw_param_defs = list(job.get_params())
    param_defs = collections.OrderedDict()
    for param in raw_param_defs:
        param_name = param['name']
        if param_name in param_defs:
            continue
        param_def = {}
        param_type = param['type']
        param_extra_description = ''
        if param_type in ('StringParameterDefinition',
                          # TODO(harlowja): can we do validation?
                          'ValidatingStringParameterDefinition'):
            param_def['type'] = str
        elif param_type == 'BooleanParameterDefinition':
            param_def['type'] = bool
            param_def['converter'] = hu.strict_bool_from_string
        elif param_type == 'ChoiceParameterDefinition':
            param_def['type'] = str
            choices = list(p.strip() for p in param['choices'] if p.strip())
            choices.sort()
            param_def['converter'] = functools.partial(utils.only_one_of,
                                                       choices)
            param_extra_description = "one of [%s]" % (", ".join(choices))
        else:
            raise RuntimeError("Unknown how to translate jenkins job '%s'"
                               " param '%s' type '%s' into a"
                               " python type: %s" % (job_name, param_name,
                                                     param_type, param))
        if 'defaultParameterValue' in param:
            param_def['default'] = param['defaultParameterValue']['value']
        if 'description' in param:
            param_description = param['description']
            if param_extra_description:
                # Do some cleanup on the existing description before
                # we mess with it (so that it formats nicer).
                param_description = param_description.strip()
                param_description = param_description.rstrip(".")
                param_description += " " + param_extra_description
            param_def['help'] = param_description
        elif param_extra_description:
            param_def['help'] = param_extra_description
        param_defs[param_name] = param_def

    args_converters = {}
    args_order = []
    args_defaults = {}
    args_help = {}
    for param_name, param_def in param_defs.items():
        args_order.append(param_name)
        if 'converter' in param_def:
            args_converters[param_name] = param_def['converter']
        if 'default' in param_def:
            args_defaults[param_name] = param_def['default']
        if 'help' in param_def:
            args_help[param_name] = param_def['help']

    handles_what['triggers'] = [
        trigger.Trigger(trigger_text, takes_args=bool(args_order)),
    ]

    handles_what['args']['help'] = args_help
    handles_what['args']['defaults'] = args_defaults
    handles_what['args']['converters'] = args_converters
    handles_what['args']['order'] = args_order

    if not description:
        description = "Initiates a %s build." % job_name

    job_cls_dct = {
        'handles_what': handles_what,
        'job_name': job_name,
        '__doc__': description,
        '__module__': __name__,
    }
    job_type_name = job_name
    job_type_name = job_type_name.replace("-", "_")
    job_type_name = job_type_name.replace(" ", "_")
    job_type_name = job_type_name.replace("\t", "_")
    job_type_name_pieces = job_type_name.split("_")
    for i in compat_range(0, len(job_type_name_pieces)):
        p = job_type_name_pieces[i]
        p = p.strip()
        if p:
            job_type_name_pieces[i] = p.title()
        else:
            job_type_name_pieces[i] = ''
    job_type_name = "%sJobHandler" % ("".join(job_type_name_pieces))
    job_type_name = str(job_type_name)
    job_cls = type(job_type_name, (JobHandler,), job_cls_dct)
    return (job_type_name, job_cls, job_cls_dct)
