from __future__ import absolute_import

import functools
import logging
import re

from apscheduler.triggers import cron
from cachetools import LRUCache
import jira
import munch
from oslo_utils import reflection
from six.moves import zip as compat_zip

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
from padre import schema_utils as scu
from padre import slack_utils as su
from padre import trigger
from padre import utils

LOG = logging.getLogger(__name__)

_ISSUE_PRIORITIES_COLORS = {
    'blocker': su.COLORS.red,
    'critical': su.COLORS.red,
    'major': su.COLORS.orange,
    'minor': su.COLORS.yellow,
    'trivial': su.COLORS.yellow,
}
_DAY_MATCHER = re.compile(r"^\s*(\d+)\s*(?:days|day|d)?\s*$", re.I)
_MIN_MATCHER = re.compile(r"^\s*(\d+)\s*(?:minutes|minute|m)?\s*$", re.I)
_SEC_MATCHER = re.compile(r"^\s*(\d+)\s*(?:seconds|second|s)?\s*$", re.I)
_HR_MATCHER = re.compile(r"^\s*(\d+)\s*(?:hours|hour|h)?\s*$", re.I)
_TIME_SPLITTER = re.compile(r"(?:\s+and\s+)|(?:\s*[,]\s*)", re.I)
_RESOLVED_TRANSITIONS = frozenset(['resolved', 'resolve issue'])


def _convert_time_taken(v):
    total_secs = 0
    total_matches = 0
    v_pieces = _TIME_SPLITTER.split(v)
    m_seen = {
        'second': False,
        'minute': False,
        'hour': False,
        'day': False,
    }
    for v_p in v_pieces:
        v_p_matched = False
        for secs_multiplier, matcher, kind in [(1, _SEC_MATCHER, 'second'),
                                               (60, _MIN_MATCHER, 'minute'),
                                               (3600, _HR_MATCHER, 'hour'),
                                               (86400, _DAY_MATCHER, 'day')]:
            m = matcher.match(v_p)
            if m:
                m_seen_already = m_seen[kind]
                if m_seen_already:
                    raise ValueError("Incorrect time definition, %s have"
                                     " already been matched" % (kind + "s"))
                n = int(m.group(1))
                if n <= 0:
                    raise ValueError("Incorrect %s definition"
                                     " %s must be a"
                                     " positive (greater than zero)"
                                     " integer" % (kind, n))
                m_seen[kind] = True
                secs_taken = n * secs_multiplier
                total_secs += secs_taken
                v_p_matched = True
                break
        if v_p_matched:
            total_matches += 1
    if len(v_pieces) != total_matches:
        raise ValueError("Incorrect time definition, could"
                         " not fully match: %s" % v)
    return total_secs


def _extract_issue_fields(issue):
    fields = []
    issue_fields = issue.fields
    try:
        fields.append({
            "title": "Priority",
            "value": issue_fields.priority.name,
            "short": True,
        })
    except AttributeError:
        pass
    try:
        fields.append({
            "title": "Status",
            "value": issue_fields.status.name,
            "short": True,
        })
    except AttributeError:
        pass
    try:
        fields.append({
            "title": "Project",
            "value": issue_fields.project.name,
            "short": True,
        })
    except AttributeError:
        pass
    return fields


def _convert_issue_to_attachment(issue):
    attachment = {
        'fallback': "Issue '%s'" % issue.key,
        'mrkdwn_in': [],
        'footer': "JIRA",
        # TODO: find a better one?
        'footer_icon': ('http://www.userlogos.org/files/logos/'
                        '14505_deva/jira1.png'),
    }
    try:
        attachment['author_name'] = issue.fields.reporter.displayName
    except AttributeError:
        pass
    description = issue.fields.description
    if description:
        description = description.strip()
    if description:
        attachment['text'] = description
    summary = issue.fields.summary
    if summary:
        summary = summary.strip()
    if summary:
        attachment['title'] = summary
        attachment['title_link'] = issue.permalink()
    try:
        issue_priority = issue.fields.priority.name
        issue_priority = issue_priority.lower()
        attachment['color'] = _ISSUE_PRIORITIES_COLORS[issue_priority]
    except (AttributeError, KeyError):
        pass
    fields = _extract_issue_fields(issue)
    if fields:
        attachment['fields'] = fields
    return attachment


def _convert_event_to_attachment(browse_base_url, event_type, event):
    issue_fields = event.issue.fields
    if event_type == 'issue_updated':
        try:
            issue_status = issue_fields.status.name
            issue_status = issue_status.lower()
            if issue_status not in ['open', 'resolved']:
                # Skip all of these.
                return None
        except AttributeError:
            pass
    issue_user = event.user
    attachment = {
        'fallback': "Received %s event." % event_type,
        'mrkdwn_in': [],
        'footer': "JIRA",
        # TODO: find a better one?
        'footer_icon': ('http://www.userlogos.org/files/logos/'
                        '14505_deva/jira1.png'),
    }
    try:
        attachment['author_name'] = issue_user.displayName
    except AttributeError:
        pass
    try:
        issue_priority = issue_fields.priority.name
        issue_priority = issue_priority.lower()
        attachment['color'] = _ISSUE_PRIORITIES_COLORS[issue_priority]
    except (AttributeError, KeyError):
        pass
    # Why isn't this in the event itself...
    issue_human_url = browse_base_url
    issue_human_url += event.issue.key
    if event_type == 'issue_updated':
        try:
            issue_event_type_name = event.issue_event_type_name
        except AttributeError:
            issue_event_type_name = ''
        if issue_event_type_name == 'issue_commented':
            pretext_tpl = ("Issue <%(issue_human_url)s|%(issue_key)s>"
                           " updated with a comment.")
        else:
            pretext_tpl = ("Issue <%(issue_human_url)s|%(issue_key)s>"
                           " updated.")
        pretext = pretext_tpl % {
            'issue_human_url': issue_human_url,
            'issue_key': event.issue.key,
        }
    elif event_type == 'issue_created':
        pretext_tpl = ("Issue <%(issue_human_url)s|%(issue_key)s>"
                       " created.")
        pretext = pretext_tpl % {
            'issue_human_url': issue_human_url,
            'issue_key': event.issue.key,
        }
    elif event_type == 'issue_deleted':
        pretext_tpl = ("Issue <%(issue_human_url)s|%(issue_key)s>"
                       " deleted.")
        pretext = pretext_tpl % {
            'issue_human_url': issue_human_url,
            'issue_key': event.issue.key,
        }
    else:
        pretext = "Received unknown issue event `%s`." % event_type,
    description = issue_fields.get("description")
    if description:
        cleaned_description = description.strip()
        if cleaned_description:
            attachment['text'] = cleaned_description
    summary = issue_fields.get("summary")
    if summary:
        attachment['title'] = summary
        attachment['title_link'] = issue_human_url
    fields = _extract_issue_fields(event.issue)
    if fields:
        attachment['fields'] = fields
    if pretext:
        attachment['mrkdwn_in'].append("pretext")
        attachment['pretext'] = pretext
    return attachment


class BroadcastEventHandler(handler.Handler):
    """Handler that turns jira events into slack messages."""
    event_formatters = {
        'issue_updated': _convert_event_to_attachment,
        'issue_created': _convert_event_to_attachment,
        'issue_deleted': _convert_event_to_attachment,
    }
    config_section = 'jira'
    template_subdir = 'jira'
    handles_what = {
        'message_matcher': matchers.match_jira(),
        'channel_matcher': matchers.match_channel(c.BROADCAST),
    }
    requires_slack_sender = True

    @classmethod
    def handles(cls, message, channel, config):
        channel_matcher = cls.handles_what['channel_matcher']
        if not channel_matcher(channel):
            return None
        message_matcher = cls.handles_what['message_matcher']
        if not message_matcher(message, cls):
            return None
        try:
            event_channels = list(config.event_channels)
        except AttributeError:
            event_channels = []
        if event_channels:
            _base, event_type = message.kind.split("/", 1)
            if event_type in cls.event_formatters:
                return handler.HandlerMatch()
            else:
                return None
        else:
            return None

    def _emit_event(self, event_type, event, out_channels):
        if not out_channels:
            return
        converter_func = self.event_formatters.get(event_type)
        if converter_func is None:
            return
        attachment = converter_func(self.config.urls.browse,
                                    event_type, event)
        if attachment:
            for out_channel in out_channels:
                self.bot.slack_sender.post_send(
                    channel=out_channel,
                    text=' ', link_names=True,
                    as_user=True, unfurl_links=True,
                    attachments=[attachment], log=LOG)

    def _run(self, **kwargs):
        _base, event_type = self.message.kind.split("/", 1)
        event = self.message.body
        self._emit_event(event_type, event,
                         self.config.event_channels)


class Unfurler(handler.Handler):
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.BROADCAST),
    }
    config_on_off = ("unfurl", False)
    required_clients = ('jira',)
    config_section = 'jira'
    cache = (None, None)
    cache_refresh = 600

    @classmethod
    def handles(cls, message, channel, config):
        channel_matcher = cls.handles_what['channel_matcher']
        if not channel_matcher(channel):
            return None
        message_matcher = cls.handles_what['message_matcher']
        if (not message_matcher(message, cls, only_to_me=False) or
                # Skip threaded entries...
                message.body.thread_ts):
            return None
        projects, projects_matchers = cls.cache
        if not projects:
            return None
        unfurl_projects = config.get("unfurl_projects")
        matches = {}
        for p, p_matcher in compat_zip(projects, projects_matchers):
            if (not p_matcher or
                    (unfurl_projects is not None and
                     p.key not in unfurl_projects)):
                continue
            p_matches = p_matcher.findall(message.body.text_no_links)
            if p_matches:
                matches[p.key] = set(p_matches)
        if not matches:
            return None
        else:
            return handler.ExplicitHandlerMatch({'matches': matches})

    @classmethod
    def insert_periodics(cls, bot, scheduler):
        def refresh_projects(jira_client):
            """Periodic loads and caches jira projects."""
            try:
                projects = jira_client.projects()
            except jira.JIRAError:
                LOG.warn("Failed fetching jira projects", exc_info=True)
            else:
                projects_matchers = []
                for p in projects:
                    p_key = p.key
                    if not p_key:
                        p_matcher = None
                    else:
                        p_matcher = re.compile(re.escape(p_key) + r"[-]\d+")
                    projects_matchers.append(p_matcher)
                cls.cache = (projects, projects_matchers)
        try:
            jira_client = bot.clients.jira_client
        except AttributeError:
            pass
        else:
            refresh_projects_name = reflection.get_callable_name(
                refresh_projects)
            refresh_projects_description = refresh_projects.__doc__
            scheduler.add_job(
                refresh_projects,
                trigger=cron.CronTrigger.from_crontab(
                    "*/10 * * * *", timezone=bot.config.tz),
                args=(jira_client,),
                jobstore='memory',
                name="\n".join([refresh_projects_name,
                                refresh_projects_description]),
                # Run right when scheduler starts up...
                next_run_time=bot.date_wrangler.get_now(),
                id=utils.hash_pieces([refresh_projects_name,
                                      refresh_projects_description],
                                     max_len=8),
                coalesce=True)

    def _run(self, matches):
        jac = self.bot.clients.jira_client
        attachments = []
        for p_key in sorted(matches.keys()):
            for raw_issue in sorted(matches[p_key]):
                try:
                    issue = jac.issue(raw_issue)
                except jira.JIRAError:
                    pass
                else:
                    attachments.append(_convert_issue_to_attachment(issue))
        if attachments:
            self.message.reply_attachments(
                channel=self.message.body.channel,
                text=None, link_names=True,
                as_user=True, unfurl_links=True,
                attachments=attachments, log=LOG,
                thread_ts=self.message.body.ts)


class UnplannedHandler(handler.TriggeredHandler):
    """Creates a unplanned issue + associates it to an active sprint."""

    # Because the client library fetches things over and over
    # and things we know to be the same, aren't changing a lot/ever...
    #
    # Size of these was picked somewhat arbitrarily but should be fine...
    cache = munch.Munch({
        'projects': LRUCache(maxsize=100),
        'boards': LRUCache(maxsize=100),
    })
    required_clients = ('jira',)
    config_section = 'jira'
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('jira unplanned', takes_args=True),
        ],
        'args': {
            'order': [
                'summary',
                'time_taken',
                'was_resolved',
                'project',
                'board',
            ],
            'converters': {
                'time_taken': _convert_time_taken,
                'was_resolved': hu.strict_bool_from_string,
            },
            'schema': Schema({
                Required("summary"): All(scu.string_types(), Length(min=1)),
                Required("project"): All(scu.string_types(), Length(min=1)),
                Required("board"): All(scu.string_types(), Length(min=1)),
                Required("time_taken"): int,
                Required("was_resolved"): bool,
            }),
            'help': {
                'summary': "short summary of the unplanned work",
                'board': 'board to locate sprint to'
                         ' drop newly created issue in (must exist)',
                'time_taken': ('time taken on unplanned'
                               ' work (ie 30 seconds, 5 minutes,'
                               ' 1 hour, 1 day...)'),
                'project': 'project to create task in (must exist)',
                'was_resolved': 'mark the newly created issue as resolved',
            },
            'defaults': {
                'project': 'CAA',
                'board': 'CAA board',
                'time_taken': "1 hour",
                "was_resolved": True,
            },
        },
        'authorizer': auth.user_in_ldap_groups('admins_cloud'),
    }

    @staticmethod
    def _find_and_cache(fetcher_func, match_func,
                        cache_target, cache_key):
        if cache_key and cache_key in cache_target:
            return cache_target[cache_key]
        offset = 0
        result = None
        found = False
        while not found:
            items = fetcher_func(start_at=offset)
            if not items:
                break
            else:
                for item in items:
                    if match_func(item):
                        result = item
                        found = True
                        break
                if not found:
                    offset = offset + len(items) + 1
        if found and cache_key:
            cache_target[cache_key] = result
        return result

    @classmethod
    def _find_project(cls, jac, project):

        def match_func(p):
            return (p.name.lower() == project.lower() or
                    p.key.lower() == project.lower() or
                    p.id == project)

        def fetcher_func(all_projects, start_at):
            return all_projects[start_at:]

        return cls._find_and_cache(
            functools.partial(fetcher_func, jac.projects()), match_func,
            cls.cache.projects, project)

    @classmethod
    def _find_board(cls, jac, board, type='scrum'):

        def match_func(b):
            return (b.name.lower() == board.lower() or
                    b.id == board)

        def fetcher_func(start_at):
            return jac.boards(type=type, startAt=start_at)

        return cls._find_and_cache(fetcher_func, match_func,
                                   cls.cache.boards, ":".join([board, type]))

    @classmethod
    def _find_sprint(cls, jac, board, board_name, ok_states):

        def match_func(s):
            return s.state.lower() in ok_states

        def fetcher_func(start_at):
            return jac.sprints(board.id, startAt=start_at)

        # We don't want to cache anything, since we expect sprints to
        # actually become active/inactive quite a bit...
        return cls._find_and_cache(fetcher_func, match_func, {}, None)

    @staticmethod
    def _create_issue(jac, project, secs_taken,
                      summary, user_name, channel_name='',
                      quick_link=None):
        mins_taken = secs_taken / 60.0
        hours_taken = mins_taken / 60.0
        days_taken = hours_taken / 24.0
        time_taken_pieces = [
            "%0.2f days" % (days_taken),
            "%0.2f hours" % (hours_taken),
            "%0.2f minutes" % (mins_taken),
            "%s seconds" % (secs_taken),
        ]
        time_taken_text = " or ".join(time_taken_pieces)
        new_issue_description_lines = [
            ("User @%s spent %s doing"
             " unplanned work.") % (user_name, time_taken_text),
        ]
        if channel_name:
            new_issue_description_lines.extend([
                "",
                "In channel: #%s" % channel_name,
            ])
        if quick_link:
            new_issue_description_lines.extend([
                "",
                "Reference: %s" % quick_link,
            ])
        new_issue_fields = {
            'summary': summary,
            'issuetype': {
                'name': 'Task',
            },
            'components': [{'name': "Unplanned"}],
            'assignee': {
                'name': user_name,
            },
            'project': project.id,
            'description': "\n".join(new_issue_description_lines),
        }
        new_issue = jac.create_issue(fields=new_issue_fields)
        new_issue_link = "<%s|%s>" % (new_issue.permalink(), new_issue.key)
        return (new_issue, new_issue_link)

    def _run(self, summary, time_taken, was_resolved, project, board):
        # Load and validate stuff (before doing work...)
        jac = self.bot.clients.jira_client
        replier = functools.partial(self.message.reply_text,
                                    threaded=True, prefixed=False)
        # This one is used here because it appears the the RTM one isn't
        # processing/sending links correctly (did it ever, but this one
        # does handle links right, so ya...)
        reply_attachments = functools.partial(
            self.message.reply_attachments,
            log=LOG, link_names=True, as_user=True,
            thread_ts=self.message.body.ts,
            channel=self.message.body.channel, unfurl_links=False)
        j_project = self._find_project(jac, project)
        if not j_project:
            raise excp.NotFound("Unable to find project '%s'" % (project))
        j_board = self._find_board(jac, board)
        if not j_board:
            raise excp.NotFound("Unable to find board '%s'" % (board))
        # Create it in that project...
        replier("Creating unplanned issue"
                " in project `%s`, please wait..." % (project))
        new_issue, new_issue_link = self._create_issue(
            jac, j_project, time_taken, summary,
            self.message.body.user_name,
            channel_name=self.message.body.get('channel_name'),
            quick_link=self.message.body.get('quick_link'))
        reply_attachments(attachments=[{
            'pretext': ("Created unplanned"
                        " issue %s.") % (new_issue_link),
            'mrkdwn_in': ['pretext'],
        }])
        # Find and bind it to currently active sprint (if any)...
        j_sprint = self._find_sprint(jac, j_board, board, ['active'])
        if j_sprint:
            reply_attachments(attachments=[{
                'pretext': ("Binding %s to active sprint `%s`"
                            " of board `%s`." % (new_issue_link,
                                                 j_sprint.name, board)),
                'mrkdwn_in': ['pretext'],
            }])
            jac.add_issues_to_sprint(j_sprint.id, [new_issue.key])
            reply_attachments(attachments=[{
                'pretext': ("Bound %s to active sprint `%s`"
                            " of board `%s`." % (new_issue_link,
                                                 j_sprint.name, board)),
                'mrkdwn_in': ['pretext'],
            }])
        else:
            replier("No active sprint found"
                    " in board `%s`, sprint binding skipped." % (board))
        # Mark it as done...
        if was_resolved:
            transition = None
            possible_transitions = set()
            for t in jac.transitions(new_issue.id):
                t_name = t.get('name', '')
                t_name = t_name.lower()
                if t_name in _RESOLVED_TRANSITIONS:
                    transition = t
                if t_name:
                    possible_transitions.add(t_name)
            if not transition:
                possible_transitions = sorted(possible_transitions)
                possible_transitions = " or ".join([
                    "`%s`" % t.upper() for t in possible_transitions])
                ok_transitions = sorted(_RESOLVED_TRANSITIONS)
                ok_transitions = " or ".join([
                    "`%s`" % t.upper() for t in ok_transitions])
                reply_attachments(attachments=[{
                    'pretext': ("Unable to resolve %s, could not find"
                                " issues %s"
                                " state transition!") % (
                                    new_issue_link,
                                    ok_transitions),
                    'mrkdwn_in': ['pretext', 'text'],
                    "text": ("Allowable state"
                             " transitions: %s" % possible_transitions),
                }])
            else:
                reply_attachments(attachments=[{
                    'pretext': ("Transitioning %s issue to resolved, "
                                "please wait...") % (new_issue_link),
                    'mrkdwn_in': ['pretext'],
                }])
                jac.transition_issue(new_issue.id, transition['id'],
                                     comment="All done! kthxbye")
                replier("Transitioned.")
        replier = self.message.reply_text
        replier("Thanks for tracking your unplanned work!",
                prefixed=True, threaded=True)
