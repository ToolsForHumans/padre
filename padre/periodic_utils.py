# -*- coding: utf-8 -*-

import itertools
import logging

from apscheduler.schedulers import base
import futurist
import munch

from padre import channel as c
from padre import date_utils as du
from padre import finishers
from padre import message as m
from padre import slack_utils as su
from padre import utils
from padre.watchers import slack as slack_watcher

LOG = logging.getLogger(__name__)


def make_periodic_runner(what, target_cls, period, channel,
                         args=None, log=None):
    """Returns a function that apscheduler can call periodically.

    This function will allow for targeting some other slack handler with
    periodic (internally made) messages so that existing handlers can be
    targeted by messages (that do not orginate from slack but instead
    originate from the scheduler itself).
    """
    if args is None:
        args = {}
    if log is None:
        log = LOG

    def runner(bot, slack_client, slack_sender):
        try:
            self_id = slack_client.server.login_data['self']['id']
        except (TypeError, KeyError):
            self_id = None
        if not self_id:
            return
        attachments = [
            {
                'pretext': ("Initiating %s that runs with"
                            " cron schedule `%s`." % (what, period)),
                'mrkdwn_in': ['pretext'],
            },
        ]
        # This sends an initial 'kick' message that the rest of the
        # work will be rooted from (ie a subthread of).
        resp = slack_sender.post_send(
            attachments=attachments, channel=channel,
            as_user=True, link_names=True,
            text="Good %s." % bot.date_wrangler.get_when())
        m_headers = {
            m.VALIDATED_HEADER: True,
            m.TO_ME_HEADER: True,
            m.CHECK_AUTH_HEADER: False,
            m.ARGS_HEADER: args.copy(),
            m.DIRECT_CLS_HEADER: target_cls,
            m.IS_INTERNAL_HEADER: True,
        }
        m_channel_id = resp["channel"]
        m_body = munch.Munch({
            'channel': m_channel_id,
            'channel_name': channel,
            'channel_kind': su.ChannelKind.convert(m_channel_id),
            'ts': resp['ts'],
            'thread_ts': None,
            'directed': False,
            'targets': [
                self_id,
            ],
            'user_id': self_id,
            'user_name': '',
            # NOTE: not used since args header passed in which turns the
            # match that is made into a explicit match (which then means
            # the text is not matched).
            'text': '',
            'text_no_links': '',
        })
        message = slack_watcher.SlackMessage(
            "slack/message", m_headers, m_body,
            slack_sender)
        su.insert_quick_link(
            message, slack_base_url=bot.config.slack.get('base_url'))
        fut = bot.submit_message(
            message, c.TARGETED,
            # Avoid using the bot executors so that we don't cause
            # cycles (a user can trigger a periodic to manually run
            # and doing that will cause a thread to wait; so it can
            # be possible to deplete both pools if this is abused).
            executor=futurist.SynchronousExecutor())
        fut.add_done_callback(
            finishers.notify_slack_on_fail(bot, message, log=log))
        fut.result()

    return runner


def format_job(job):
    """Turns job (from `format_scheduler`) -> slack attachment."""
    attachment_fields = [
        {
            'title': "Entrypoint",
            "value": job.name,
            'short': utils.is_short(job.name),
        },
        {
            "title": "State",
            "value": job.state,
            "short": True,
        },
        {
            "title": "Trigger",
            "short": utils.is_short(job.trigger),
            "value": job.trigger,
        },
    ]
    if job.runs_in is not None:
        job_runs_in = utils.format_seconds(job.runs_in)
        attachment_fields.append({
            "title": "Runs in",
            "value": job_runs_in,
            "short": utils.is_short(job_runs_in),
        })
    return {
        "pretext": u"• Job `%s`" % (job.id),
        'mrkdwn_in': ['pretext'],
        'text': job.description,
        'fields': attachment_fields,
    }


def format_scheduler(sched, tz=None):
    """Turns the scheduler instance into something useful to show others."""
    if tz is None:
        tz = sched.timezone
    now = du.get_now(tz=tz)
    seen_jobs = set()
    jobs = {
        'PAUSED': [],
        'PENDING_OR_RUNNING': [],
    }
    for job in sched.get_jobs():
        if job.id in seen_jobs:
            continue
        seen_jobs.add(job.id)
        job_runs_in = None
        job_next_run_time = job.next_run_time
        if job_next_run_time is None:
            job_state = 'PAUSED'
        else:
            job_state = 'PENDING_OR_RUNNING'
            job_runs_in = job_next_run_time - now
            job_runs_in = job_runs_in.total_seconds()
        if job.name:
            job_name_lines = job.name.splitlines()
        else:
            job_name_lines = []
        try:
            job_name = job_name_lines[0]
        except IndexError:
            job_name = ''
        job_description = "\n".join(job_name_lines[1:])
        jobs[job_state].append(
            munch.Munch({
                'id': job.id,
                'name': job_name,
                # TODO: also get this upstream... so that we don't have
                # to do the splitlines and such...
                'description': job_description.strip(),
                'state': job_state,
                'runs_in': job_runs_in,
                'trigger': str(job.trigger),
            }))
    jobs_pending_running = jobs['PENDING_OR_RUNNING']
    jobs_pending_running = sorted(jobs_pending_running,
                                  key=lambda job: job.runs_in)
    if sched.state == base.STATE_STOPPED:
        sched_state = 'STOPPED'
    elif sched.state == base.STATE_RUNNING:
        sched_state = 'RUNNING'
    elif sched.state == base.STATE_PAUSED:
        sched_state = 'PAUSED'
    else:
        sched_state = "UNKNOWN"
    return sched_state, list(itertools.chain(jobs_pending_running,
                                             jobs['PAUSED']))
