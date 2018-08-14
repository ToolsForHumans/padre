# -*- coding: utf-8 -*-

import datetime
import functools
import logging
import random

import iso8601
import munch
from oslo_utils import netutils
from oslo_utils import uuidutils
import pytz
import shade

from voluptuous import All
from voluptuous import Any
from voluptuous import Length
from voluptuous import Required
from voluptuous import Schema

from padre import authorizers as auth
from padre import channel as c
from padre import cloud_utils as cu
from padre import exceptions as excp
from padre import followers
from padre import handler
from padre import handler_utils as hu
from padre import matchers
from padre import schema_utils as su
from padre import trigger

LOG = logging.getLogger(__name__)


def _convert_dt(default_timezone, v):
    if v is None:
        return None
    else:
        return iso8601.parse_date(v, default_timezone=default_timezone)


def _dummy_replier(msg):
    pass


def _force_exact(thing):
    # This is likely not (fully) comprehensive but should at least escape
    # most of what we would be getting to hit mysql REGEXP... (we should
    # really make it possible to tell nova to do exact searches via
    # a REST api param).
    #
    # NOTE: the | symbol is not currently in this list since it appears
    # nova at a low low level will escape this already (and if we escape
    # it here, then nova will double escape it and that would not result
    # in the correct query); this is weird and someone should fix this
    # upstream (since afaik its not known unless u read the code).
    #
    # See: nova/db/sqlalchemy/api.py (_safe_regex_mysql function).
    for ch in ["^", "$", ".", "(", ")",
               "[", "]", "+", "?", "{", "}", "-", "*"]:
        ch_loc = thing.find(ch)
        if ch_loc == -1:
            continue
        thing = thing.replace(ch, "\\" + ch)
    # We don't want regex searching enabled, so for certain fields we
    # want to ensure they force exact matches (as much as we can).
    return "^" + thing + "$"


class Searcher(object):
    """Mixin that aids in activities related to searching various clouds."""

    def _search(self, thing, filters,
                only_private=True, target_search=True,
                cloud='', replier=None, expand_images=True):
        if replier is None:
            replier = _dummy_replier
        replier("Loading all"
                " the %s, please wait..." % random.choice(cu.CLOUDS))
        topos = []
        for env_name in self.bot.topo_loader.env_names:
            topo = self.bot.topo_loader.load_one(env_name)
            if topo.cloud.kind != 'production':
                continue
            if only_private and topo.cloud.type != 'private':
                continue
            if (cloud and cloud not in (topo.cloud.name,
                                        topo.cloud.canonical_name)):
                continue
            topos.append(topo)
        found = []
        searched_clouds = 0
        replier("Searching %s clouds, please wait..." % len(topos))
        if topos:
            configs = {}
            for topo in topos:
                config = topo.render('os_client_config')
                configs[topo.cloud.canonical_name] = config
            for cloud_name in sorted(configs.keys()):
                if self.dead.is_set():
                    replier("I am dying, try again later...")
                    raise excp.Dying
                replier("Searching `%s`..." % cloud_name)
                searched_clouds += 1
                config = configs[cloud_name]
                cloud_config = config.get_one_cloud(cloud=cloud_name)
                cloud = shade.OpenStackCloud(cloud_config=cloud_config)
                found_servers = cloud.list_servers(
                    detailed=False, bare=False, all_projects=True,
                    filters=filters)
                if found_servers:
                    found.append((cloud, cloud_name, found_servers))
                    if target_search:
                        break  # Found what we wanted. Skip other clouds
        servers = []
        found_clouds = []
        for cloud, cloud_name, found_servers in found:
            if self.dead.is_set():
                replier("I am dying, try again later...")
                raise excp.Dying
            found_clouds.append(cloud_name)
            if expand_images:
                cloud_images = cloud.list_images(filter_deleted=False)
                cloud_images_by_id = dict((image.id, image)
                                          for image in cloud_images)
                for s in found_servers:
                    try:
                        s_image_id = s.image.id
                        s.image = cloud_images_by_id[s_image_id]
                    except (KeyError, AttributeError):
                        pass
            servers.extend(found_servers)
        return servers, searched_clouds, found_clouds

    def _emit_servers(self, servers):
        attachments = []
        for server in servers:
            attachment_fields = [
                {
                    'title': 'Name',
                    'value': server.name,
                    'short': True,
                },
                {
                    'title': 'ID',
                    'value': server.id,
                    'short': True,
                },
                {
                    'title': 'State',
                    'value': server.status,
                    'short': True,
                },
            ]
            try:
                attachment_fields.append({
                    'title': 'Cloud',
                    'value': server.location.cloud,
                    'short': True,
                })
            except AttributeError:
                pass
            for ip_type in ('fixed', 'floating'):
                for server_ip in cu.iter_ips_of_type(server, ip_type):
                    attachment_fields.append({
                        'title': 'IP address',
                        'value': "%s (%s)" % (server_ip, ip_type),
                        'short': True,
                    })
            try:
                attachment_fields.append({
                    'title': 'Availability zone',
                    'value': server.az,
                    'short': True,
                })
            except AttributeError:
                pass
            try:
                attachment_fields.append({
                    'title': 'Image',
                    'value': server.image.name,
                    'short': True,
                })
            except AttributeError:
                pass
            try:
                attachment_fields.append({
                    'title': 'Project',
                    'value': server.metadata.project_name,
                    'short': True,
                })
            except AttributeError:
                pass
            try:
                attachment_fields.append({
                    'title': 'Owning group',
                    'value': server.metadata.owning_group,
                    'short': True,
                })
            except AttributeError:
                pass
            try:
                attachment_fields.append({
                    'title': 'Created by',
                    'value': server.metadata.created_by,
                    'short': True,
                })
            except AttributeError:
                pass
            try:
                server_hv = server['OS-EXT-SRV-ATTR:hypervisor_hostname']
                attachment_fields.append({
                    'title': 'Hypervisor',
                    'value': server_hv,
                    'short': True,
                })
            except KeyError:
                pass
            attachment_fields = sorted(
                attachment_fields, key=lambda field: field['title'].lower())
            attachments.append({
                'pretext': ('Server `%s` launched'
                            ' on `%s`.') % (server.name, server.launched_at),
                'mrkdwn_in': ['pretext'],
                'fields': attachment_fields,
            })
        self.message.reply_attachments(
            attachments=attachments,
            log=LOG, link_names=True,
            as_user=True, thread_ts=self.message.body.ts,
            channel=self.message.body.channel,
            unfurl_links=False)


class ListServersOnHypervisor(Searcher, handler.TriggeredHandler):
    """Lists virtual machines on a hypervisor."""

    requires_topo_loader = True
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('openstack hypervisor list-vms', takes_args=True),
        ],
        'args': {
            'order': [
                'hypervisor',
                'only_private',
                'cloud',
            ],
            'help': {
                'hypervisor': 'hypervisor to list vms on',
                'only_private': ('only search the private clouds'
                                 ' and skip the public clouds'),
                'cloud': ("filter to only specific cloud (empty"
                          " searches all clouds)"),
            },
            'converters': {
                'only_private': hu.strict_bool_from_string,
            },
            'schema': Schema({
                Required("hypervisor"): All(su.string_types(), Length(min=1)),
                Required("only_private"): bool,
                Required("cloud"): su.string_types(),
            }),
            'defaults': {
                'only_private': True,
                'cloud': '',
            },
        },
        'authorizer': auth.user_in_ldap_groups('admins_cloud_viewers'),
    }

    def _run(self, hypervisor, only_private=True, cloud=''):
        replier = functools.partial(self.message.reply_text,
                                    threaded=True, prefixed=False)
        servers, searched_clouds, _found_clouds = self._search(
            hypervisor, {'host': hypervisor}, target_search=True,
            only_private=only_private, cloud=cloud, replier=replier)
        if servers:
            self._emit_servers(servers)
            replier("Found %s possible matches, hopefully one of"
                    " them was what you were looking for..." % len(servers))
        else:
            replier("Sorry I could not find `%s` in %s clouds,"
                    " try another?" % (hypervisor, searched_clouds))


class NotifyOwnersOfServersOnHypervisor(Searcher, handler.TriggeredHandler):
    """Notify some owners of VMs on a hypervisor about something."""

    requires_topo_loader = True
    required_clients = ('ecm',)
    confirms_action = 'notification'
    confirms_what = 'something'
    template_subdir = 'maintenance'
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger(
                'openstack hypervisor notify-vm-owners', takes_args=True),
        ],
        'args': {
            'order': [
                'hypervisor',
                'template',
                'what',
                'description',
                'when',
                'only_private',
                'cloud',
                # Various ecm passthroughs...
                'test_mode',
                'notify_slack',
                'notify_email',
            ],
            'help': {
                'hypervisor': 'hypervisor to find vms on',
                'template': "notification template to use",
                'what': 'one word for what is about to happen',
                'when': ("when the event is going to happen"
                         " in iso8601 format (if not"
                         " provided then the current time is used)"),
                'description': 'multiple words for what is about to happen',
                'only_private': ('only search the private clouds'
                                 ' and skip the public clouds'),
                'cloud': ("filter to only specific cloud (empty"
                          " searches all clouds)"),
                # Various ecm passthroughs...
                'test_mode': 'ecm notification api test mode passthrough',
                'notify_slack': 'send notification via slack',
                'notify_email': 'send notification via email',
            },
            # This will be filled in during setup_class call (since it
            # needs semi-dynamic information from the bot configuration).
            'converters': {},
            'schema': Schema({
                Required("hypervisor"): All(su.string_types(), Length(min=1)),
                Required("only_private"): bool,
                Required("cloud"): su.string_types(),
                Required("what"): All(su.string_types(), Length(min=1)),
                Required("description"): All(su.string_types(), Length(min=1)),
                Required("template"): All(su.string_types(), Length(min=1)),
                Required("when"): Any(None, datetime.datetime),
                # Various ecm passthroughs...
                Required("test_mode"): bool,
                Required("notify_email"): bool,
                Required("notify_slack"): bool,
            }),
            'defaults': {
                'only_private': True,
                'cloud': '',
                'when': None,
                # Various ecm passthroughs...
                'test_mode': False,
                'notify_slack': True,
                'notify_email': True,
            },
        },
        'authorizer': auth.user_in_ldap_groups('admins_cloud'),
    }

    @classmethod
    def setup_class(cls, bot):
        tz = bot.config.tz
        cls.handles_what['args']['converters'].update({
            'only_private': hu.strict_bool_from_string,
            'when': functools.partial(_convert_dt, pytz.timezone(tz)),
            # Various ecm passthroughs...
            'test_mode': hu.strict_bool_from_string,
            'notify_slack': hu.strict_bool_from_string,
            'notify_email': hu.strict_bool_from_string,
        })

    def _build_template(self, servers, hypervisor, template,
                        what, when, description, test_mode=False):
        tmp_servers = []
        for s in servers:
            s_owner = None
            try:
                s_owner = s.metadata.owning_group
            except AttributeError:
                pass
            if s_owner:
                # Present a smaller view of which servers are here (for now).
                tmp_servers.append(munch.Munch({
                    'id': s.id,
                    'owner': s_owner,
                    'name': s.name,
                }))
        subject = self.render_template('hv_subject', {'what': what.title()})
        subject = subject.strip()
        body = self.render_template(template, {
            'hypervisor': hypervisor,
            'vms': tmp_servers,
            'what': what,
            'description': description,
            'when': when,
            'subject': subject,
            'test_mode': test_mode,
        })
        return subject, body

    def _run(self, hypervisor, template, what, description,
             when=None, only_private=True, cloud='', test_mode=False,
             notify_email=True, notify_slack=True):
        ecm = self.bot.clients.ecm_client
        replier = functools.partial(self.message.reply_text,
                                    threaded=True, prefixed=False)
        if when is None:
            when = self.date_wrangler.get_now()
        if not self.template_exists(template):
            replier("Template `%s` does not exist. Try again." % template)
        else:
            servers, searched_clouds, _found_clouds = self._search(
                hypervisor, {'host': hypervisor}, target_search=True,
                only_private=only_private, cloud=cloud, replier=replier)
            if servers:
                self._emit_servers(servers)
                subject, body = self._build_template(servers, hypervisor,
                                                     template, what, when,
                                                     description,
                                                     test_mode=test_mode)
                attachment = {
                    'pretext': (
                        "Found %s servers hosted on hypervisor `%s`, please"
                        " confirm that you wish to notify owners"
                        " of these servers using bundled template"
                        " `%s`." % (len(servers), hypervisor, template)),
                    'text': "\n".join([
                        "_Subject:_ `%s`" % subject,
                        "_Body:_",
                        '```',
                        body,
                        '```',
                    ]),
                    'mrkdwn_in': ["text", 'pretext'],
                }
                self.message.reply_attachments(
                    attachments=[attachment],
                    log=LOG, link_names=True,
                    as_user=True, text=' ',
                    thread_ts=self.message.body.ts,
                    channel=self.message.body.channel,
                    unfurl_links=False)
                f = followers.ConfirmMe(confirms_what='notification')
                replier(f.generate_who_satisifies_message(self))
                self.wait_for_transition(wait_timeout=300,
                                         wait_start_state='CONFIRMING',
                                         follower=f)
                if self.state != 'CONFIRMED_CANCELLED':
                    self.change_state("SPAMMING")
                    admin_owning_group = self.config.get('admin_owning_group')
                    sent, _unknowns, targets = ecm.notify_server_owners(
                        servers, subject, body, test_mode=test_mode,
                        notify_email=notify_email, notify_slack=notify_slack,
                        admin_owning_group=admin_owning_group)
                    if sent:
                        replier(
                            "Notification spam"
                            " sent (via slack and/or email) to %s"
                            " groups." % (len(targets)))
                    else:
                        replier("Spam not sent (either no targets found"
                                " or no requested spam mechanisms"
                                " provided).")
                else:
                    replier("Notification cancelled.")
            else:
                replier("Sorry I could not find `%s` in %s clouds,"
                        " try another?" % (hypervisor, searched_clouds))


class DescribeServerHandler(Searcher, handler.TriggeredHandler):
    """Finds a virtual machine and describes it.

    This is on purpose eerily similar to OSC `server show` command.
    """

    requires_topo_loader = True
    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('openstack server show', takes_args=True),
        ],
        'args': {
            'order': [
                'server',
                'only_private',
                'cloud',
            ],
            'help': {
                'server': 'server (name or id)',
                'only_private': ('only search the private clouds'
                                 ' and skip the public clouds'),
                'cloud': ("filter to only specific cloud (empty"
                          " searches all clouds)"),
            },
            'converters': {
                'only_private': hu.strict_bool_from_string,
            },
            'schema': Schema({
                Required("server"): All(su.string_types(), Length(min=1)),
                Required("only_private"): bool,
                Required("cloud"): su.string_types(),
            }),
            'defaults': {
                'only_private': True,
                'cloud': '',
            },
        },
        'authorizer': auth.user_in_ldap_groups('admins_cloud_viewers'),
    }

    def _run(self, server, only_private=True, cloud=''):
        # Search should be unique across clouds
        target_search = True
        if uuidutils.is_uuid_like(server):
            # Find by UUID
            filters = {'uuid': server}
        elif netutils.is_valid_ip(server):
            # Find by IP address
            # Note: Much more expensive. Calling when exactly like an IP.
            filters = {'ip': _force_exact(server)}
        else:
            # Find by name (across all clouds)
            filters = {'name': _force_exact(server)}
            target_search = False  # Name could exist in multiple clouds
        replier = functools.partial(self.message.reply_text,
                                    threaded=True, prefixed=False)
        servers, searched_clouds, _found_clouds = self._search(
            server, filters, target_search=target_search,
            only_private=only_private,
            cloud=cloud, replier=replier)
        if servers:
            self._emit_servers(servers)
            replier("Found %s possible matches, hopefully one of"
                    " them was what you were looking for..." % len(servers))
        else:
            replier("Sorry I could not find `%s` in %s clouds,"
                    " try another?" % (server, searched_clouds))
