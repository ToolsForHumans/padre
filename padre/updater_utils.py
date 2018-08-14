# -*- coding: utf-8 -*-

import collections
import re

from distutils.version import LooseVersion

import artifactory

from padre import exceptions as excp

# Ignore all the old style git sha based versions that we can't
# determine meaningful numbers from; we turned these off at a point
# but we can't seem to delete them fully from artifactory...
OLD_BUSTED_RE = re.compile(r"(.*)(\d\.\d\.\d)(\.g[a-z0-9]+)(\.j\d+)$", re.I)

VersionedPath = collections.namedtuple("VersionedPath", "version,path")


def _is_good_artifactory_path(path):
    # TODO: until we get this working skip this...
    if path.name == "latest":
        return False
    m = OLD_BUSTED_RE.match(path.name)
    if m is not None:
        return False
    for sub_path in path.iterdir():
        if sub_path.name == 'manifest.json':
            return True
    return False


def _iter_valid_paths(ro_account, project_url):
    path = artifactory.ArtifactoryPath(
        project_url, verify=True,
        auth=(ro_account.username, ro_account.password))
    for sub_path in path.iterdir():
        if _is_good_artifactory_path(sub_path):
            yield sub_path


def extract_labels(path):
    m_path = None
    if path.name == 'manifest.json':
        m_path = path
    else:
        for p in path.iterdir():
            if p.name == 'manifest.json':
                m_path = p
                break
    m_labels = {}
    if m_path is not None:
        for k, v in m_path.properties.items():
            if k.startswith('docker.label.'):
                try:
                    k = k.split(".", 2)[2]
                except IndexError:
                    pass
                else:
                    m_labels[k] = v
    return m_labels


def extract_changelog(path, reformat=True):
    labels = extract_labels(path)
    tmp_lines = []
    for k, v in labels.items():
        m = re.match(r'^CHANGELOG_(\d+)$', k)
        if m:
            tmp_lines.append((int(m.group(1)), v[0]))
    tmp_lines = sorted(tmp_lines, key=lambda v: v[0])
    tmp_lines = [v for _num, v in tmp_lines]
    lines = []
    if reformat:
        for line in tmp_lines:
            line = line.replace("\_", "_")
            if line.startswith("*"):
                line = u"•" + line[1:]
            lines.append(line)
    else:
        lines = tmp_lines
    return lines


def check_fetch_version(check_version, ro_account, project_url):
    path = artifactory.ArtifactoryPath(
        project_url, verify=True,
        auth=(ro_account.username, ro_account.password))
    found_path = None
    busted = False
    for sub_path in path.iterdir():
        if sub_path.name != check_version:
            continue
        if not _is_good_artifactory_path(sub_path):
            found_path = sub_path
            busted = True
            break
        else:
            found_path = sub_path
            break
    if found_path is not None and busted:
        raise excp.NotFound(
            "Version '%s' was not found as a valid subpath"
            " under '%s'" % (check_version, project_url))
    if found_path is None:
        raise excp.NotFound(
            "Version '%s' was not found under"
            " '%s'" % (check_version, project_url))
    return VersionedPath(LooseVersion(found_path.name), found_path)


def iter_updates(me_version, ro_account, project_url):
    for path in _iter_valid_paths(ro_account, project_url):
        v_path = VersionedPath(LooseVersion(path.name), path)
        if v_path.version > me_version:
            yield v_path
