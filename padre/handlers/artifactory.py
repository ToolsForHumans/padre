# -*- coding: utf-8 -*-

from __future__ import absolute_import

import collections
import functools
import json
import logging
import math
import urllib

import artifactory
import munch
from oslo_utils import strutils

from voluptuous import All
from voluptuous import Length
from voluptuous import Range
from voluptuous import Required
from voluptuous import Schema

from padre import authorizers as auth
from padre import channel as c
from padre import exceptions as excp
from padre import followers
from padre import handler
from padre import matchers
from padre import schema_utils as su
from padre import trigger
from padre import utils


LOG = logging.getLogger(__name__)
ART_ICON = ('https://www.jfrog.com/wp-content/uploads/'
            '2015/09/JFrog-Logo-trans-cut-300x287.png')


def _calc_emit_every(items):
    # Every 10% a progress bar will update telling everyone
    # that another 10% have been finished... this function calculates
    # how many items are in each 10% block...
    item_am = len(items)
    segs = item_am * 0.10
    segs = int(math.ceil(segs))
    return max(1, segs)


def _format_dt(dt):
    return dt.strftime("%m/%d/%Y")


def _is_frozen(path):
    props = path.properties
    return any([strutils.bool_from_string(props.get("frozen", False)),
                strutils.bool_from_string(props.get("deployed", False))])


def _calc_docker_size(path, starting_size):
    # This tries to do a smart analysis of the docker manifest json
    # file to determine all the sizes, instead of using the recursive
    # size calculator (this speeds things up drastically if it is useable).
    #
    # It will abort at any problem or suspected issue (the recursive
    # calculator is the fallback...)
    tot_size = starting_size
    sub_paths = dict((sub_path.name, sub_path) for sub_path in path.iterdir())
    manifest_path = sub_paths.get('manifest.json')
    if manifest_path is None:
        raise excp.NotFound
    try:
        with manifest_path.open() as fh:
            manifest_contents = json.loads(fh.read())
    except (IOError, ValueError):
        raise excp.NotFound
    check_paths = [manifest_contents.get("config")]
    check_paths.extend(manifest_contents.get("layers", []))
    tot_looked_at = 1
    for p in check_paths:
        if not p:
            continue
        try:
            p_digest = p['digest']
        except KeyError:
            raise excp.NotFound
        p_digest = p_digest.replace(":", "__")
        if p_digest not in sub_paths:
            raise excp.NotFound
        try:
            tot_size += int(p["size"])
        except (KeyError, TypeError, ValueError):
            raise excp.NotFound
        else:
            tot_looked_at += 1
    if tot_looked_at != len(sub_paths):
        raise excp.NotFound
    return tot_size


def _iter_sizes_deep(path):
    curr_elems = collections.deque([path])
    seen = set()
    while curr_elems:
        p = curr_elems.popleft()
        if p in seen:
            continue
        seen.add(p)
        p_stat = p.stat()
        yield p_stat.size
        if p.is_dir():
            curr_elems.extend(p.iterdir())


def _find_path(conf, project, acct):
    project_url = conf.base_url
    if not project_url.endswith("/"):
        project_url += "/"
    project_url += 'artifactory/docker-cloud-'
    project_url += urllib.quote(project)
    project_url += "-local"
    path = artifactory.ArtifactoryPath(project_url, verify=True,
                                       auth=(acct.username, acct.password))
    if path.exists() and path.is_dir():
        return path
    return None


class PruneHandler(handler.TriggeredHandler):
    """Prunes a docker artifactory repositories."""

    config_section = 'artifactory'
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('artifactory prune', takes_args=True),
        ],
        'authorizer': auth.user_in_ldap_groups('admins_cloud'),
        'args': {
            'order': ['project', 'target_size'],
            'help': {
                'project': 'project to scan',
                'target_size': 'target size to prune project repo to',
            },
            'schema': Schema({
                Required("project"): All(su.string_types(), Length(min=1)),
                Required("target_size"): All(int, Range(min=0)),
            }),
            'converters': {
                'target_size': functools.partial(strutils.string_to_bytes,
                                                 return_int=True,
                                                 # Because artifactory
                                                 # is using the SI
                                                 # system... arg...
                                                 unit_system='SI'),
            },
        },
    }
    required_secrets = (
        'ci.artifactory.ro_account',
        'ci.artifactory.push_account',
    )
    required_configurations = ('base_url',)

    def _do_prune(self, prune_what):
        dirs_pruned = 0
        files_pruned = 0
        was_finished = True
        pbar = self.message.make_progress_bar(
            len(prune_what), update_period=_calc_emit_every(prune_what))
        for child in pbar.wrap_iter(prune_what):
            if self.dead.is_set():
                was_finished = False
                break
            stack = collections.deque()
            stack.append((child.path, False))
            while stack:
                # NOTE: we do not check dead.is_set() here which might
                # be ok, but is done so that we don't delete a sub child
                # half-way (which if done may leave any docker images
                # half-way-working... ie missing components/layers...
                # which would be bad).
                p, p_visited = stack.pop()
                p_is_dir = p.is_dir()
                if p_is_dir and not p_visited:
                    stack.append((p, True))
                    stack.extend((c_p, False) for c_p in p.iterdir())
                elif p_is_dir and p_visited:
                    p.rmdir()
                    dirs_pruned += 1
                else:
                    p.unlink()
                    files_pruned += 1
        return (dirs_pruned, files_pruned, was_finished)

    def _do_scan(self, replier, path, target_size):
        root_child_paths = list(path.iterdir())
        all_sub_children = []
        replier("Finding all sub-children of"
                " %s top-level children." % len(root_child_paths))

        if root_child_paths:
            pbar = self.message.make_progress_bar(
                len(root_child_paths),
                update_period=_calc_emit_every(root_child_paths))
            for child_path in pbar.wrap_iter(root_child_paths):
                if self.dead.is_set():
                    raise excp.Dying
                replier("Scanning top-level"
                        " child `%s`, please wait..." % child_path.name)
                sub_child_paths = list(child_path.iterdir())
                if sub_child_paths:
                    rc_pbar = self.message.make_progress_bar(
                        len(sub_child_paths),
                        update_period=_calc_emit_every(sub_child_paths))
                    for sub_child_path in rc_pbar.wrap_iter(sub_child_paths):
                        if self.dead.is_set():
                            raise excp.Dying
                        all_sub_children.append(munch.Munch({
                            'path': sub_child_path,
                            'frozen': _is_frozen(sub_child_path),
                            'ctime': sub_child_path.stat().ctime,
                            'size': sub_child_path.stat().size,
                            'parent': child_path,
                        }))

        all_sub_children = sorted(all_sub_children, key=lambda p: p.ctime)
        num_childs_frozen = sum(int(sc.frozen) for sc in all_sub_children)
        replier("Determining total sizes"
                " of %s sub-children"
                " (%s are frozen)." % (len(all_sub_children),
                                       num_childs_frozen))
        if all_sub_children:
            pbar = self.message.make_progress_bar(
                len(all_sub_children),
                update_period=_calc_emit_every(all_sub_children))
            for sub_child in pbar.wrap_iter(all_sub_children):
                if self.dead.is_set():
                    raise excp.Dying
                try:
                    total_size = _calc_docker_size(sub_child.path,
                                                   sub_child.size)
                except excp.NotFound:
                    total_size = 0
                    for size in _iter_sizes_deep(sub_child.path):
                        if self.dead.is_set():
                            raise excp.Dying
                        total_size += size
                sub_child.total_size = total_size

        accum_size = 0
        prune_what = []
        for sub_child in reversed(all_sub_children):
            if sub_child.frozen:
                continue
            accum_size += sub_child.total_size
            if accum_size >= target_size:
                prune_what.append(sub_child)
        prune_what.reverse()
        return prune_what

    def _format_child(self, child):
        try:
            child_pretext = "%s/%s" % (child.parent.name, child.path.name)
        except AttributeError:
            child_pretext = "%s" % child.path.name
        attachment = {
            'pretext': child_pretext,
            'mrkdwn_in': [],
            'footer': "Artifactory",
            'footer_icon': ART_ICON,
        }
        tot_size = utils.format_bytes(child.total_size)
        attachment['fields'] = [
            {
                'title': 'Size',
                'value': tot_size,
                'short': utils.is_short(tot_size),
            },
            {
                "title": "Created on",
                "value": _format_dt(child.ctime),
                "short": True,
            },
        ]
        return attachment

    def _run(self, project, target_size):
        push_account = self.bot.secrets.ci.artifactory.push_account
        path = _find_path(self.config, project, push_account)
        if not path:
            raise excp.NotFound("Could not find project '%s'" % project)
        replier = functools.partial(self.message.reply_text,
                                    threaded=True, prefixed=False)
        replier("Scanning `%s`, please wait..." % project)
        try:
            prune_what = self._do_scan(replier, path, target_size)
        except excp.Dying:
            replier("Died during scanning, please try"
                    " again next time...")
            return
        if not prune_what:
            replier("Nothing to prune found.")
            return
        self.message.reply_attachments(
            attachments=list(self._format_child(c) for c in prune_what),
            log=LOG, link_names=True, as_user=True,
            thread_ts=self.message.body.ts,
            channel=self.message.body.channel)
        replier("Please confirm the pruning of"
                " %s paths." % len(prune_what))
        f = followers.ConfirmMe(confirms_what='pruning')
        replier(f.generate_who_satisifies_message(self))
        self.wait_for_transition(wait_timeout=300, follower=f,
                                 wait_start_state='CONFIRMING')
        if self.state != 'CONFIRMED_CANCELLED':
            self.change_state("PRUNING")
            replier("Initiating prune of %s paths." % len(prune_what))
            dirs_pruned, files_pruned, done = self._do_prune(prune_what)
            replier("Pruned %s directories and"
                    " %s files." % (dirs_pruned, files_pruned))
            if not done:
                replier("This was a partial prune, since I died"
                        " during pruning, please try"
                        " again next time...")
        else:
            replier("Pruning cancelled.")


class CalcSizeHandler(handler.TriggeredHandler):
    """Determines size of docker artifactory repositories."""

    config_section = 'artifactory'
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('artifactory calculate size', takes_args=True),
        ],
        'authorizer': auth.user_in_ldap_groups('admins_cloud'),
        'args': {
            'order': ['project'],
            'help': {
                'project': 'project to scan',
            },
            'schema': Schema({
                Required("project"): All(su.string_types(), Length(min=1)),
            }),
        },
    }
    required_secrets = (
        'ci.artifactory.ro_account',
    )
    required_configurations = ('base_url',)

    def _run(self, project):
        ro_account = self.bot.secrets.ci.artifactory.ro_account

        path = _find_path(self.config, project, ro_account)
        if not path:
            raise excp.NotFound("Could not find project '%s'" % project)

        replier = self.message.reply_text
        replier = functools.partial(replier, threaded=True, prefixed=False)
        replier("Determining current size of `%s`, please"
                " wait..." % project)

        all_sizes = [
            path.stat().size,
        ]
        child_paths = list(path.iterdir())
        child_paths = sorted(child_paths, key=lambda p: p.name)
        if child_paths:
            c_pbar = self.message.make_progress_bar(
                len(child_paths), update_period=_calc_emit_every(child_paths))
            for child_path in c_pbar.wrap_iter(child_paths):
                if self.dead.is_set():
                    break
                all_sizes.append(child_path.stat().size)
                replier("Determining total size"
                        " of top-level child `%s`, please"
                        " wait..." % child_path.name)
                sub_child_paths = list(child_path.iterdir())
                if sub_child_paths:
                    sc_pbar = self.message.make_progress_bar(
                        len(sub_child_paths),
                        update_period=_calc_emit_every(sub_child_paths))
                    for sub_child_path in sc_pbar.wrap_iter(sub_child_paths):
                        if self.dead.is_set():
                            break
                        try:
                            sub_child_size = _calc_docker_size(
                                sub_child_path, sub_child_path.stat().size)
                        except excp.NotFound:
                            sub_child_size = 0
                            for size in _iter_sizes_deep(sub_child_path):
                                if self.dead.is_set():
                                    break
                                sub_child_size += size
                        all_sizes.append(sub_child_size)

        if self.dead.is_set():
            replier("Died during scanning, please"
                    " try again next time...")
        else:
            replier(
                "Size of `%s` is %s" % (project,
                                        utils.format_bytes(
                                            sum(all_sizes), quote=True)))
