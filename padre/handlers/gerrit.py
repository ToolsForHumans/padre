import json
import logging
import re

import munch
from oslo_utils import reflection
import requests

from padre import channel as c
from padre import handler
from padre import matchers
from padre import utils

LOG = logging.getLogger(__name__)


def _filter_by_project(ok_projects, event):
    in_projects = [
        event.change.project,
    ]
    send_message = False
    for project in ok_projects:
        if project in in_projects:
            send_message = True
            break
        if project == "*":
            send_message = True
            break
    return send_message


def _filter_by_email(known_emails, email_suffixes, event):
    incoming_emails = []
    incoming_emails.append(event.change.owner.email)
    incoming_emails.append(event.patch_set.author.email)
    incoming_emails.append(event.patch_set.uploader.email)
    incoming_emails.append(event.uploader.email)
    incoming_emails = set(email for email in incoming_emails
                          if email is not None)
    send_message = False
    if any(e in known_emails for e in incoming_emails):
        send_message = True
    email_suffixes = [e.strip() for e in email_suffixes if e.strip()]
    if len(email_suffixes) == 0:
        send_message = True
    else:
        for ok_suffix in email_suffixes:
            if ok_suffix == "*":
                send_message = True
            else:
                for in_email in incoming_emails:
                    if in_email.endswith(ok_suffix):
                        send_message = True
    return send_message


class Unfurler(handler.TriggeredHandler):
    handles_what = {
        'channel_matcher': matchers.match_channel(c.BROADCAST),
        'message_matcher': matchers.match_slack("message"),
    }
    template_subdir = 'gerrit'
    config_section = 'gerrit'
    config_on_off = ("unfurl.enabled", False)
    change_url_tpl = ("%(base)s://%(host)s/changes/%(change_id)s"
                      "?o=CURRENT_COMMIT&o=CURRENT_REVISION")
    change_msg_tpl = ("`{{ change.subject }}` in"
                      " project `{{ change.project }}`"
                      " ({{ change.insertions }}|{{ change.deletions }}).")

    @classmethod
    def _find_matches(cls, message_text, config):
        matches = []
        expand_for = []
        try:
            expand_for = list(config.unfurl.expand_for)
        except AttributeError:
            pass
        for tmp_host in expand_for:
            pats = [
                r"(https://|http://)" + tmp_host + r"/#/c/(\d+)[/]?",
                r"(https://|http://)" + tmp_host + r"/(\d+)[/]?",
            ]
            for pat in pats:
                for m in re.finditer(pat, message_text):
                    match = munch.Munch({
                        'host': tmp_host,
                        'change_id': int(m.group(2)),
                        'url': m.group(0),
                    })
                    if m.group(1) == "https://":
                        match.is_secure = True
                    else:
                        match.is_secure = False
                    matches.append(match)
        return matches

    def _fetch_change(self, match, call_timeout):
        base = "http"
        if match.is_secure:
            base += "s"
        change_url = self.change_url_tpl % {
            'base': base,
            'host': match.host,
            'change_id': match.change_id,
        }
        change = None
        try:
            req = requests.get(change_url, timeout=call_timeout)
            req.raise_for_status()
        except requests.RequestException:
            LOG.warning("Failed fetch of change %s from '%s'",
                        match.change_id, change_url, exc_info=True)
        else:
            # Rip off the header gerrit responses start with.
            body_lines = req.text.split("\n")[1:]
            body = "\n".join(body_lines)
            try:
                change = json.loads(body)
                if not isinstance(change, dict):
                    raise TypeError(
                        "%s is not a dict" % reflection.get_class_name(change))
            except (ValueError, TypeError):
                LOG.warning("Received invalid json content from result"
                            " of call to %s", change_url, exc_info=True)
            else:
                LOG.debug("Received %s", change)
                change = munch.munchify(change)
        return change

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
        matches = cls._find_matches(message_text, config)
        if not matches:
            return None
        return handler.ExplicitHandlerMatch(arguments={
            'matches': matches,
        })

    @staticmethod
    def _find_author(change):
        maybe_author = []
        if hasattr(change, 'owner') and change.owner:
            maybe_author.extend([
                change.owner.get("name"),
                change.owner.get("email"),
                change.owner.get("username"),
            ])
        rev = change.revisions[change.current_revision]
        if hasattr(rev, "commit") and rev.commit:
            committer = rev.commit.get("committer", {})
            maybe_author.extend([
                committer.get("name"),
                committer.get("email"),
                committer.get("username"),
            ])
        author = None
        for a in maybe_author:
            if a:
                author = a
                break
        return author

    def _run(self, matches=None):
        if not matches:
            matches = []
        seen_changes = set()
        replier = self.message.reply_attachments
        for m in matches:
            if self.dead.is_set():
                break
            if m.change_id <= 0:
                continue
            m_ident = (m.host, m.change_id)
            if m_ident in seen_changes:
                continue
            seen_changes.add(m_ident)
            LOG.debug("Trying to unfurl '%s'", m.url)
            change = self._fetch_change(m, self.config.unfurl.call_timeout)
            if change is not None:
                attachment = {
                    'fallback': change.subject,
                    'pretext': utils.render_template(
                        self.change_msg_tpl, {'change': change}),
                    'link': m.url,
                    'footer': "Gerrit",
                    'mrkdwn_in': ["pretext"],
                    'footer_icon': ("https://upload.wikimedia.org/"
                                    "wikipedia/commons/thumb/4/4d/"
                                    "Gerrit_icon.svg/"
                                    "52px-Gerrit_icon.svg.png"),
                }
                author = self._find_author(change)
                if author:
                    attachment['author_name'] = author
                rev = change.revisions[change.current_revision]
                if rev.commit and rev.commit.message:
                    attachment['text'] = rev.commit.message.strip()
                replier(channel=self.message.body.channel,
                        log=LOG, thread_ts=self.message.body.ts,
                        attachments=[attachment],
                        link_names=False, as_user=True,
                        unfurl_links=False)


class PatchSetCreatedHandler(handler.Handler):
    """Handlers incoming gerrit patch set created events (not from users)."""
    config_section = 'gerrit'
    template_subdir = 'gerrit'
    handles_what = {
        'channel_matcher': matchers.match_channel(c.BROADCAST),
        'message_matcher': matchers.match_gerrit("patchset-created"),
    }
    requires_slack_sender = True

    @staticmethod
    def _passes_filters(target, what):
        passes = _filter_by_email(target.get("emails", []),
                                  target.get("email_suffixes", []),
                                  what)
        if not passes:
            return False
        passes = _filter_by_project(target.get("projects", []), what)
        if not passes:
            return False
        return True

    def _run(self):
        what = self.message.body
        targets = []
        for target in self.config.get('channels', []):
            if self._passes_filters(target, what):
                targets.append(target)
        if targets:
            attachment = {
                'pretext': self.render_template("change", what),
                'mrkdwn_in': ["pretext"],
            }
            expanded_attachment = attachment.copy()
            expanded_attachment.update({
                'text': what.change.commit_message.strip(),
                'footer': "OpenStack Gerrit",
                'footer_icon': ("https://upload.wikimedia.org/"
                                "wikipedia/commons/thumb/4/4d/"
                                "Gerrit_icon.svg/52px-Gerrit_icon.svg.png"),
            })
            for target in targets:
                if self.dead.is_set():
                    break
                if target.get("expand", True):
                    tmp_attachment = expanded_attachment
                else:
                    tmp_attachment = attachment
                self.bot.slack_sender.post_send(
                    channel=target.channel,
                    text=' ', attachments=[tmp_attachment],
                    link_names=True, as_user=True,
                    unfurl_links=False, log=LOG)
