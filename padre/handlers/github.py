# -*- coding: utf-8 -*-

from __future__ import absolute_import

import functools
import logging
import os
import re
import urlparse
from UserString import MutableString

import git
import munch
import pytz

from voluptuous import All
from voluptuous import Length
from voluptuous import MultipleInvalid
from voluptuous import Optional
from voluptuous import Required
from voluptuous import Schema

from padre import channel as c
from padre import git_utils
from padre import handler
from padre import matchers
from padre import process_utils
from padre import schema_utils as scu
from padre import slack_utils as su
from padre import trigger
from padre import utils


LOG = logging.getLogger(__name__)


def _format_pr_fields(gh_pr, now=None):
    fields = [
        {
            "title": "State",
            "value": str(gh_pr.state.title()),
            "short": True,
        },
        {
            "title": "Mergeable",
            "value": str(gh_pr.mergeable),
            "short": True,
        },
    ]
    if gh_pr.additions > 0:
        add_val = "+" + str(gh_pr.additions)
    else:
        add_val = "0"
    if gh_pr.deletions > 0:
        del_val = "-" + str(gh_pr.deletions)
    else:
        del_val = "0"
    fields.extend([
        {
            "title": "Additions",
            "value": add_val,
            "short": True,
        },
        {
            "title": "Deletions",
            "value": del_val,
            "short": True,
        },
    ])
    if now is not None:
        created_at_diff = now - gh_pr.created_at
        created_at_diff_secs = created_at_diff.total_seconds()
        created_at = utils.format_seconds(created_at_diff_secs)
        fields.append({
            'title': 'Age',
            'value': created_at,
            "short": utils.is_short(created_at),
        })
    return sorted(fields, key=lambda v: v['title'].lower())


def _extract_orgs_repos(orgs_repos):
    entries = []
    for entry in orgs_repos.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            org, repo = entry.split("/", 1)
            repo = repo.strip()
        except ValueError:
            org = entry
            repo = ''
        org = org.strip()
        if not org:
            raise ValueError("Organization must be present"
                             " in entry '%s'" % entry)
        entry = (org, repo)
        if entry not in entries:
            entries.append(entry)
    return sorted(entries)


class PRUnfurler(handler.TriggeredHandler):
    config_on_off = ("github.unfurl", False)
    handles_what = {
        'channel_matcher': matchers.match_channel(c.BROADCAST),
        'message_matcher': matchers.match_slack("message"),
    }
    required_clients = ('github',)
    required_configurations = ("github.base_url",)

    @staticmethod
    def _build_matcher(config):
        matcher_base_url = urlparse.urlparse(config.github.base_url)
        matcher_base_url_netloc = matcher_base_url.netloc
        if not matcher_base_url_netloc:
            return None
        matcher_base = re.escape(matcher_base_url_netloc)
        return re.compile(
            r"http(s)?://" + matcher_base + r'/(.+?)/(.+?)/pull/(\d+)',
            re.I)

    @classmethod
    def _find_matches(cls, matcher, message_text):
        matches = []
        for match in matcher.findall(message_text):
            matches.append(munch.Munch({
                'org': match[1],
                'repo': match[2],
                'pull': int(match[3]),
            }))
        return matches

    @classmethod
    def handles(cls, message, channel, config):
        channel_matcher = cls.handles_what['channel_matcher']
        if not channel_matcher(channel):
            return None
        message_matcher = cls.handles_what['message_matcher']
        if (not message_matcher(message, cls, only_to_me=False) or
                message.body.thread_ts):
            return None
        message_text = message.body.text_no_links
        matcher = cls._build_matcher(config)
        if not matcher:
            return None
        matches = cls._find_matches(matcher, message_text)
        if not matches:
            return None
        return handler.ExplicitHandlerMatch(arguments={
            'matches': matches,
        })

    @staticmethod
    def _format_pr(gh_org, gh_repo, gh_pr):
        attachment = {
            'pretext': gh_pr.title,
            'text': gh_pr.body,
            'fields': _format_pr_fields(gh_pr),
        }
        try:
            attachment['author_name'] = gh_pr.user.name
            attachment['author_link'] = gh_pr.user.html_url
        except AttributeError:
            pass
        return attachment

    def _run(self, matches=None):
        if not matches:
            matches = []
        seen = set()
        gh = self.bot.clients.github_client
        attachments = []
        for m in matches:
            if self.dead.is_set():
                break
            m_ident = (m.org, m.repo, m.pull)
            if m_ident in seen:
                continue
            seen.add(m_ident)
            try:
                gh_org = gh.get_organization(m.org)
                gh_repo = gh_org.get_repo(m.repo)
                gh_pr = gh_repo.get_pull(m.pull)
            except Exception:
                LOG.warning(
                    "Failed fetching needed data for %s, skipping it...", m,
                    exc_info=True)
            else:
                attachments.append(self._format_pr(gh_org, gh_repo, gh_pr))
        if attachments:
            self.message.reply_attachments(
                channel=self.message.body.channel,
                link_names=True, as_user=True, unfurl_links=True,
                attachments=attachments, log=LOG,
                thread_ts=self.message.body.ts)


class PRScanReportHandler(handler.TriggeredHandler):
    """Scans configured github orgs & repos and produces a PR report."""

    config_section = 'github'
    required_clients = ('github',)
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('pull request report', takes_args=True),
        ],
        'args': {
            'order': [
                'org_repo',
            ],
            'converters': {
                'org_repo': _extract_orgs_repos,
            },
            'schema': Schema({
                Required("org_repo"): All(list, Length(min=1)),
            }),
            'help': {
                'org_repo': ("organization and/or organization/repo to"
                             " interrogate (comma separated if many)"),
            },
        },
    }

    @staticmethod
    def _determine_age(pull, now):
        if pull.created_at > now:
            return 'From the _future_'
        created_at_diff = now - pull.created_at
        created_at_diff_secs = created_at_diff.total_seconds()
        if created_at_diff_secs <= (12 * 3600):
            return "*Very* _fresh_"
        if created_at_diff_secs <= 86400:
            return "_Fresh_"
        if created_at_diff_secs <= (3 * 86400):
            return "*Mostly* _fresh_"
        if created_at_diff_secs <= (7 * 86400):
            return "_Molding_"
        if created_at_diff_secs <= (14 * 86400):
            return "*Heavily* _molding_"
        if created_at_diff_secs <= (21 * 86400):
            return "_Rotting_"
        if created_at_diff_secs <= (28 * 86400):
            return "*Heavily* _rotting_"
        return "*Unidentifiable*"

    @classmethod
    def _iter_pull_attachments(cls, now, pulls):
        for p in sorted(pulls, key=lambda p: p.pull.created_at):
            attachment = {
                'pretext': u"• %s PR created by <%s|%s>" % (
                    cls._determine_age(p.pull, now), p.pull.user.html_url,
                    p.pull.user.name),
                'mrkdwn_in': ["pretext"],
                'text': p.pull.title,
                'title': ("%s/%s - PR #%s") % (p.org_name,
                                               p.repo_name,
                                               p.pull.number),
                'title_link': p.pull.html_url,
                'fields': _format_pr_fields(p.pull, now=now),
            }
            yield attachment

    def _run(self, org_repo):
        gh = self.bot.clients.github_client
        replier = functools.partial(self.message.reply_text,
                                    threaded=True, prefixed=False)

        # TODO: The pygithub api seems to drop timestamps TZ (seems to always
        # be in zulu time, so due to this we can't use our timezone
        # specific comparison)... file a bug sometime.
        now = self.date_wrangler.get_now()
        now = now.astimezone(pytz.UTC)
        now = now.replace(tzinfo=None)

        seen_full_orgs = set()
        for entry in org_repo:
            org_name, repo_name = entry
            if org_name in seen_full_orgs:
                continue
            if not repo_name:
                seen_full_orgs.add(org_name)
                replier("Scanning `%s` organization,"
                        " please wait..." % (org_name))
                gh_org = gh.get_organization(org_name)
                gh_org_repos = [(repo.name, repo)
                                for repo in gh_org.get_repos('public')]
                emit_repo = True
            else:
                replier("Scanning `%s/%s` organization"
                        " repository, please wait..." % (org_name,
                                                         repo_name))
                gh_org = gh.get_organization(org_name)
                gh_org_repos = [
                    (repo_name, gh_org.get_repo(repo_name)),
                ]
                emit_repo = False
            for repo_name, gh_repo in gh_org_repos:
                if emit_repo:
                    replier("Scanning `%s/%s` organization"
                            " repository, please wait..." % (org_name,
                                                             repo_name))
                gh_repo_pulls = []
                for gh_pull in gh_repo.get_pulls(state='open'):
                    gh_repo_pulls.append(munch.Munch({
                        'pull': gh_pull,
                        'repo': gh_repo,
                        'org': gh_org,
                        'org_name': org_name,
                        'repo_name': repo_name,
                    }))
                replier('Discovered `%s` open'
                        ' pull requests.' % (len(gh_repo_pulls)))
                attachments = list(
                    self._iter_pull_attachments(now, gh_repo_pulls))
                self.message.reply_attachments(
                    channel=self.message.body.channel,
                    text=None, link_names=True,
                    as_user=True, unfurl_links=True,
                    attachments=attachments, log=LOG,
                    thread_ts=self.message.body.ts)


class BroadcastEventHandler(handler.Handler):
    """Handler that turns github events into slack messages."""

    config_section = 'github'
    template_subdir = 'github'
    handles_what = {
        'message_matcher': matchers.match_github(),
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
            return handler.HandlerMatch()
        else:
            return None

    def _run(self, **kwargs):
        event_channels = list(self.config.event_channels)
        event_type = self.message.sub_kind
        if self.template_exists(event_type):
            tpl_params = self.message.body
            tpl_content = self.render_template(event_type, tpl_params)
            attachment = {
                'fallback': "Received event '%s'" % event_type,
                'mrkdwn_in': ["pretext"],
                'color': su.COLORS.green,
                'pretext': tpl_content,
                'footer': "GitHub",
                'footer_icon': ("https://assets-cdn.github.com/"
                                "images/modules/logos_page/Octocat.png"),
            }
            for channel in event_channels:
                self.bot.slack_sender.post_send(
                    channel=channel,
                    text=' ', link_names=True,
                    as_user=True, unfurl_links=True,
                    attachments=[attachment], log=LOG)
        else:
            LOG.info("Encountered unknown event '%s' (no template"
                     " exists to render it)", event_type)


class SyncHandler(handler.TriggeredHandler):
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('sync repo', True),
        ],
        'args': {
            'order': [
                'downstream_url',
                'upstream_url',
                'upstream_branch_refs',
                'upstream_tag_refs',
                'upstream_tags_as_branches_refs',
                'patch_repo_url',
                'patch_branch',
            ],
            'defaults': {
                'downstream_url': None,
                'upstream_url': None,
                'upstream_branch_refs': "master",
                'upstream_tag_refs': "",
                'upstream_tags_as_branches_refs': "",
                'patch_repo_url': "",
                'patch_branch': "master",
            },
            'converters': {},
            'schema': Schema({
                Required("downstream_url"): All(scu.string_types(),
                                                Length(min=1)),
                Required("upstream_url"): All(scu.string_types(),
                                              Length(min=1)),
                Optional("upstream_branch_refs"): All(scu.string_types(),
                                                      Length(min=1)),
                Optional("upstream_tag_refs"): scu.string_types(),
                Optional("upstream_tags_as_branches_refs"): scu.string_types(),
                Optional("patch_repo_url"): scu.string_types(),
                Optional("patch_branch"): All(scu.string_types(),
                                              Length(min=1)),
            }),
            'help': {
                'downstream_url': "Which downstream git url to sync into?",
                'upstream_url': "Which upstream git url to sync from?",
                'upstream_branch_refs':
                    "Which upstream branches to sync into downstream?",
                'upstream_tag_refs':
                    "Which upstream tags to sync into downstream?",
                'upstream_tags_as_branches_refs':
                    "Which upstream tags to sync into downstream as branches?",
            },
        },
    }
    required_clients = (
        'github',
    )
    periodic_config_path = "github.periodics"

    @staticmethod
    def _format_voluptuous_error(data, validation_error,
                                 max_sub_error_length=500):
        errors = []
        if isinstance(validation_error, MultipleInvalid):
            errors.extend(sorted(
                sub_error.path[0] for sub_error in validation_error.errors))
        else:
            errors.append(validation_error.path[0])

        errors = ['`{}`'.format(e) for e in errors]
        if len(errors) == 1:
            adj = ''
            vars = errors[0]
            verb = 'is'
        elif len(errors) == 2:
            adj = 'Both of '
            vars = ' and '.join(errors)
            verb = 'are'
        else:
            adj = 'All of '
            vars = MutableString(', '.join(errors))
            last_comma = vars.rfind(', ')
            vars[last_comma:last_comma + 2] = ', and '
            verb = 'are'

        return 'Error: {adj}{vars} {verb} required.'.format(
            adj=adj, vars=vars, verb=verb)

    def _run(self, downstream_url, upstream_url, upstream_branch_refs,
             upstream_tag_refs, upstream_tags_as_branches_refs,
             patch_repo_url, patch_branch):

        tmp_upstream_branch_refs = []
        for upstream_branch in upstream_branch_refs.split(","):
            upstream_branch = upstream_branch.strip()
            if upstream_branch:
                tmp_upstream_branch_refs.append(upstream_branch)
        upstream_branch_refs = tmp_upstream_branch_refs

        tmp_upstream_tags_refs = []
        for upstream_tag in upstream_tag_refs.split(","):
            upstream_tag = upstream_tag.strip()
            if upstream_tag:
                tmp_upstream_tags_refs.append(upstream_tag)
        upstream_tag_refs = tmp_upstream_tags_refs

        tmp_upstream_tags_as_branches_refs = []
        for upstream_tag_branch in upstream_tags_as_branches_refs.split(","):
            upstream_tag_branch = upstream_tag_branch.strip()
            if upstream_tag_branch:
                tmp_pieces = upstream_tag_branch.split(":", 2)
                tmp_tag = tmp_pieces[0]
                tmp_branch = tmp_pieces[1]
                tmp_upstream_tags_as_branches_refs.append(
                    [tmp_tag, tmp_branch])
        upstream_tags_as_branches_refs = tmp_upstream_tags_as_branches_refs

        project = upstream_url.split('/')
        project = project[-1] or project[-2]

        self.message.reply_text(
            "Syncing repository for project `%s`..." % project,
            threaded=True, prefixed=False)

        # Make temp dir for run
        tmp_dir_prefix = "github_sync_{}".format(project)
        with utils.make_tmp_dir(dir=self.bot.config.working_dir,
                                prefix=tmp_dir_prefix) as tmp_dir:
            # Clone the source repo
            try:
                source_repo = git.Repo.clone_from(
                    upstream_url, os.path.join(tmp_dir, 'source'))
                self.message.reply_text(
                    ":partyparrot: Successfully loaded repository `%s`."
                    % project, threaded=True, prefixed=False)
            except Exception:
                self.message.reply_text(
                    ":sadparrot: Failed to load repository `%s`." % project,
                    threaded=True, prefixed=False)
                return

            # Now check patches, if we know what patch repo to use
            if patch_repo_url:
                self.message.reply_text(
                    "Checking patch compatibility for `%s` branch `%s`." %
                    (project, patch_branch), threaded=True, prefixed=False)

                # Clone the patch repo
                patch_repo = git.Repo.clone_from(
                    patch_repo_url, os.path.join(tmp_dir, 'patches'))
                head_commit = patch_repo.head.commit.hexsha

                # Validate patches
                r = process_utils.run(
                    ['update-patches', '--branch-override', patch_branch,
                     '--patch-repo', patch_repo.working_dir],
                    cwd=os.path.join(tmp_dir, "source")  # from sync() above
                )
                try:
                    r.raise_for_status()
                    self.message.reply_text(
                        ":gdhotdog: Patch compatibility check successful.",
                        threaded=True, prefixed=False)
                except process_utils.ProcessExecutionError:
                    self.message.reply_text(
                        "Patch compatibility check failed. Please do a manual "
                        "rebase!", threaded=True, prefixed=False)
                    attachment = {
                        'text': (":warning:"
                                 " Patches are in merge conflict in the"
                                 " repository `%s`. Manual intervention"
                                 " is required!") % project,
                        'mrkdwn_in': ['text'],
                        'color': su.COLORS.purple,
                    }
                    self.message.reply_attachments(
                        attachments=[attachment], log=LOG,
                        as_user=True, text=' ',
                        channel=self.config.admin_channel,
                        unfurl_links=True)
                    return

                # If we made an auto-commit, PR it
                if patch_repo.head.commit.hexsha == head_commit:
                    self.message.reply_text(
                        "No patch updates detected.",
                        threaded=True, prefixed=False)
                else:
                    new_branch = '{project}_{short_hash}'.format(
                        project=project,
                        short_hash=patch_repo.head.commit.hexsha[:8])
                    new_refspec = 'HEAD:{branch}'.format(branch=new_branch)
                    self.message.reply_text(
                        "Pushing patch updates to branch `{branch}`.".format(
                            branch=new_branch), threaded=True, prefixed=False)
                    patch_repo.remote().push(refspec=new_refspec)
                    patch_repo_name = patch_repo_url.split(":")[-1]
                    patch_repo_name = patch_repo_name.split('.git')[0]
                    gh_repo = self.bot.clients.github_client.get_repo(
                        patch_repo_name)
                    title, body = patch_repo.head.commit.message.split('\n', 1)
                    self.message.reply_text(
                        "Creating pull request...",
                        threaded=True, prefixed=False)
                    pr = gh_repo.create_pull(title=title, body=body.strip(),
                                             base="master", head=new_branch)
                    self.message.reply_text(
                        ":gunter: Pull request created: {url}".format(
                            url=pr.html_url), threaded=True, prefixed=False)

            # Finish syncing the repo by pushing the new state
            self.message.reply_text(
                "Pushing upstream state downstream...",
                threaded=True, prefixed=False)
            source_repo.heads.master.checkout()
            source_repo.remote().fetch()
            retval = git_utils.sync_push(
                working_folder=tmp_dir,
                target=downstream_url,
                push_tags=upstream_tag_refs,
                push_branches=upstream_branch_refs,
                push_tags_to_branches=upstream_tags_as_branches_refs)
            if retval == 0:
                self.message.reply_text(
                    ":partyparrot: Successfully pushed repository `%s`."
                    % project, threaded=True, prefixed=False)
            else:
                self.message.reply_text(
                    ":sadparrot: Failed to push repository `%s`." % project,
                    threaded=True, prefixed=False)
                return
            self.message.reply_text(":beers: Done.",
                                    threaded=True, prefixed=False)
