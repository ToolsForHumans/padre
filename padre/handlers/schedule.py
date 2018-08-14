# -*- coding: utf-8 -*-

import logging

from voluptuous import All
from voluptuous import Length
from voluptuous import Required
from voluptuous import Schema

from padre import authorizers as auth
from padre import channel as c
from padre import exceptions as excp
from padre import handler
from padre import handler_utils as hu
from padre import matchers
from padre import periodic_utils as peu
from padre import schema_utils as scu
from padre import trigger

LOG = logging.getLogger(__name__)


class PauseHandler(handler.TriggeredHandler):
    """Pauses a periodic job."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('periodics pause', takes_args=True),
        ],
        'args': {
            'order': [
                'job_id',
            ],
            'help': {
                'job_id': 'job id to pause',
            },
            'schema': Schema({
                Required("job_id"): All(scu.string_types(), Length(min=1)),
            }),
        },
        'authorizer': auth.user_in_ldap_groups('admins_cloud'),
    }

    def _run(self, job_id):
        job = self.bot.scheduler.get_job(job_id)
        if job is None:
            raise excp.NotFound("Could not find job id '%s'" % job_id)
        if job.next_run_time is not None:
            job.pause()
            self.message.reply_text("Job `%s` has"
                                    " been paused." % job_id,
                                    threaded=True, prefixed=False)
        else:
            self.message.reply_text("Job `%s` is already"
                                    " paused." % job_id,
                                    threaded=True, prefixed=False)


class ResumeHandler(handler.TriggeredHandler):
    """Resumes a previously paused periodic job."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('periodics resume', takes_args=True),
        ],
        'args': {
            'order': [
                'job_id',
            ],
            'help': {
                'job_id': 'job id to resume',
            },
            'schema': Schema({
                Required("job_id"): All(scu.string_types(), Length(min=1)),
            }),
        },
        'authorizer': auth.user_in_ldap_groups('admins_cloud'),
    }

    def _run(self, job_id):
        job = self.bot.scheduler.get_job(job_id)
        if job is None:
            raise excp.NotFound("Could not find job id '%s'" % job_id)
        if job.next_run_time is None:
            job.resume()
            self.bot.scheduler.wakeup()
            self.message.reply_text("Job `%s` has"
                                    " been resumed." % job_id,
                                    threaded=True, prefixed=False)
        else:
            self.message.reply_text("Job `%s` is not paused (so it can"
                                    " not be resumed)." % job_id,
                                    threaded=True, prefixed=False)


class RunOneHandler(handler.TriggeredHandler):
    """Explicitly runs one periodic jobs."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('periodics run one', takes_args=True),
        ],
        'args': {
            'order': [
                'job_id',
            ],
            'help': {
                'job_id': 'job id to run',
            },
            'schema': Schema({
                Required("job_id"): All(scu.string_types(), Length(min=1)),
            }),
        },
        'authorizer': auth.user_in_ldap_groups('admins_cloud'),
    }

    def _run(self, job_id):
        job = self.bot.scheduler.get_job(job_id)
        if job is None:
            raise excp.NotFound("Could not find job id '%s'" % job_id)
        elif job.next_run_time is None:
            raise RuntimeError("Paused job '%s' can not be explicitly"
                               " ran (please resume it first)" % job_id)
        else:
            job.modify(next_run_time=self.date_wrangler.get_now())
            self.bot.scheduler.wakeup()
            self.message.reply_text("Job `%s` has had"
                                    " its next run time"
                                    " updated to be now (hopefully it"
                                    " runs soon)." % job_id,
                                    threaded=True, prefixed=False)


class RunAllHandler(handler.TriggeredHandler):
    """Explicitly runs all periodic jobs."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('periodics run all', takes_args=True),
        ],
        'args': {
            'order': [
                'skip_paused',
            ],
            'help': {
                'skip_paused': ('skip over paused jobs (ie do not'
                                ' unpause them)'),
            },
            'defaults': {
                'skip_paused': True,
            },
            'converters': {
                'skip_paused': hu.strict_bool_from_string,
            },
            'schema': Schema({
                Required("skip_paused"): bool,
            }),
        },
        'authorizer': auth.user_in_ldap_groups('admins_cloud'),
    }

    def _run(self, skip_paused):
        kicked = 0
        seen_jobs = set()
        skipped = 0
        for job in self.bot.scheduler.get_jobs():
            if job.id in seen_jobs:
                continue
            seen_jobs.add(job.id)
            if skip_paused and job.next_run_time is None:
                skipped += 1
                continue
            job.modify(next_run_time=self.date_wrangler.get_now())
            kicked += 1
        if kicked:
            self.bot.scheduler.wakeup()
        text = ("Kicked %s jobs"
                " and skipped %s jobs.") % (kicked, skipped)
        self.message.reply_text(text, threaded=True, prefixed=False)


class ShowHandler(handler.TriggeredHandler):
    """Shows the internal time schedule (for periodic jobs)."""

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('periodics show', takes_args=False),
        ],
    }

    def _run(self):
        sched_state, jobs = peu.format_scheduler(self.bot.scheduler)
        text = "Scheduler is in `%s` state" % sched_state
        if jobs:
            text += " with the following jobs:"
            self.message.reply_attachments(
                text=text, attachments=[peu.format_job(job) for job in jobs],
                log=LOG, link_names=True, as_user=True,
                thread_ts=self.message.body.ts,
                channel=self.message.body.channel)
        else:
            text += "."
            self.message.reply_text(text, threaded=True, prefixed=False)
