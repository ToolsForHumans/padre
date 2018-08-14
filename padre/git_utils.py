#!/usr/bin/python
# -*- coding: utf-8 -*-

# MIT License
#
# Modified from https://github.com/wzpan/git-repo-sync/

import os
import subprocess
import sys


def print_blocked(output):
    print("=" * len(output))
    print(output)
    print("=" * len(output))


def check_output(cmd, **kwargs):
    tmp_cmd = subprocess.list2cmdline(cmd)
    print("Running command '%s'" % tmp_cmd)
    return subprocess.check_output(cmd, **kwargs)


def call(cmd, **kwargs):
    tmp_cmd = subprocess.list2cmdline(cmd)
    print("Running command '%s'" % tmp_cmd)
    return subprocess.call(cmd, **kwargs)


def get_remote_branches(working_dir, remote, skip_branches):
    remote_branches = check_output(["git", "branch", "-r"],
                                   cwd=working_dir)
    remote_branches = remote_branches.split("\n")
    tmp_branches = []
    for branch in remote_branches:
        branch = branch.strip()
        if not branch:
            continue
        if branch.find("->") == -1:
            tmp_branches.append(branch)
        else:
            tmp_branch, tmp_alias = branch.split("->", 1)
            tmp_branch = tmp_branch.strip()
            if tmp_branch:
                tmp_branches.append(tmp_branch)
    long_branches = []
    short_branches = []
    for branch in tmp_branches:
        tmp_remote, short_branch = branch.split('/', 1)
        if tmp_remote != remote:
            continue
        if short_branch in skip_branches:
            continue
        long_branches.append(branch)
        short_branches.append(short_branch)
    return long_branches, short_branches


def get_remote_tags(remote, working_dir):
    cmd = ['git', 'ls-remote', '--tags', remote]
    tags = check_output(cmd, cwd=working_dir)
    tags = tags.split("\n")
    tmp_tags = []
    for tag in tags:
        tag = tag.strip()
        if not tag:
            continue
        tag_pieces = tag.split(None)
        if len(tag_pieces) != 2:
            continue
        tag_sha, tag = tag_pieces
        if tag.endswith("^{}"):
            continue
        if not tag.startswith("refs/tags/"):
            continue
        tag = tag[len("refs/tags/"):]
        if tag and tag not in tmp_tags:
            tmp_tags.append(tag)
    return tmp_tags


def get_local_branches(working_dir):
    local_branches = check_output(["git", "branch"], cwd=working_dir)
    local_branches = local_branches.split("\n")
    tmp_branches = []
    for branch in local_branches:
        branch = branch.replace("*", "")
        branch = branch.strip()
        if not branch:
            continue
        tmp_branches.append(branch)
    return tmp_branches


def get_local_tags(working_dir):
    local_tags = check_output(["git", "tag"], cwd=working_dir)
    local_tags = local_tags.split("\n")
    tmp_tags = []
    for tag in local_tags:
        tag = tag.strip()
        if not tag:
            continue
        tmp_tags.append(tag)
    return tmp_tags


def sync_push(working_folder, target, push_tags, push_branches,
              push_tags_to_branches):
    source_folder = os.path.join(working_folder, "source")
    res = call(['git', 'remote', 'add', 'target', target],
               cwd=source_folder)
    if res != 0:
        sys.stderr.write("Unable to add remote to %s\n" % target)
        return 1
    print_blocked("Interrogating")
    remote_branches, remote_short_branches = get_remote_branches(
        source_folder, 'origin', ['HEAD'])
    all_success = True
    branches_checked = 0
    for branch, short_branch in zip(remote_branches, remote_short_branches):
        branches_checked += 1
        print("Checking out branch '%s'" % branch)
        git_cmd = ['git', 'checkout']
        if short_branch != "master":
            git_cmd.append('-t')
        git_cmd.append(branch)
        res = call(git_cmd, cwd=source_folder)
        if res != 0:
            sys.stderr.write("Unable to checkout remote"
                             " branch '%s'\n" % (branch))
            all_success = False
        else:
            res = call(['git', 'checkout', short_branch], cwd=source_folder)
            if res != 0:
                sys.stderr.write("Unable to checkout"
                                 " branch '%s'\n" % (branch))
                all_success = False
    if not all_success:
        sys.stderr.write("Failed interrogating %s"
                         " branches\n" % (branches_checked))
        return 1
    res = call(['git', 'fetch', '-t'], cwd=source_folder)
    if res != 0:
        sys.stderr.write("Failed fetching tags\n")
        return 1
    remote_tags = get_remote_tags("target", source_folder)
    local_branches = get_local_branches(source_folder)
    local_tags = get_local_tags(source_folder)
    print_blocked("Validating")
    for tag in push_tags:
        if tag not in local_tags:
            sys.stderr.write("Unable to find tag '%s'\n" % (tag))
            return 1
    for tag_branch in push_tags_to_branches:
        tmp_tag, tmp_branch = tag_branch
        if tmp_tag not in local_tags:
            sys.stderr.write("Unable to find tag '%s'\n" % (tmp_tag))
            return 1
    for branch in push_branches:
        if branch not in local_branches:
            sys.stderr.write("Unable to find branch '%s'\n" % (branch))
            return 1
    print_blocked("Pushing")
    push_fails = 0
    branches_to_push = []
    for branch in local_branches:
        if branch not in push_branches:
            continue
        branches_to_push.append(branch)
    if branches_to_push:
        for branch in branches_to_push:
            print("Pushing branch '%s'" % (branch))
            res = call(['git', 'push', '-u', 'target', branch],
                       cwd=source_folder)
            if res != 0:
                sys.stderr.write("Pushing branch '%s' failed\n" % branch)
                push_fails += 1
    else:
        print("No branches to push.")
    tags_to_push = []
    for tag in local_tags:
        if tag in remote_tags or tag not in push_tags:
            continue
        tags_to_push.append(tag)
    if tags_to_push:
        for tag in tags_to_push:
            print("Pushing tag '%s'" % (tag))
            res = call(['git', 'push', '-u', 'target', tag],
                       cwd=source_folder)
            if res != 0:
                sys.stderr.write("Pushing tag '%s' failed\n" % tag)
                push_fails += 1
    else:
        print("No tags to push.")
    tags_to_push_as_branches = []
    for tag_branch in push_tags_to_branches:
        tmp_tag, tmp_branch = tag_branch
        tags_to_push_as_branches.append((tmp_tag, tmp_branch))
    if tags_to_push_as_branches:
        for tag, branch in tags_to_push_as_branches:
            print("Pushing tag '%s' as branch '%s'" % (tag, branch))
            res = call(['git', 'checkout', tag], cwd=source_folder)
            if res != 0:
                sys.stderr.write("Checkout of tag '%s' failed\n" % tag)
                push_fails += 1
            else:
                res = call(['git', 'checkout', "-b", branch],
                           cwd=source_folder)
                if res != 0:
                    sys.stderr.write("Checkout of branch '%s'"
                                     " failed\n" % branch)
                    push_fails += 1
                else:
                    res = call(['git', 'push', "target",
                                "%s:%s" % (branch, branch)],
                               cwd=source_folder)
                    if res != 0:
                        sys.stderr.write("Pushing tag '%s' as branch"
                                         " '%s' failed\n" % (tag, branch))
                        push_fails += 1
    else:
        print("No tags to push as branches.")
    if push_fails:
        return 1
    return 0
