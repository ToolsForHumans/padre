# -*- coding: utf-8 -*-

import collections
import contextlib
import functools
import logging
import os
import pkg_resources
import random
import re
import socket
import threading

import distance
import elasticsearch
import futurist
import github
import jira as jiraclient
import munch
from oslo_serialization import msgpackutils as mu
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import netutils
from oslo_utils import reflection
import pytz
import six
import slackclient
import sqlitedict
import tinyjenkins as tj

from apscheduler import events
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler import schedulers
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers import cron

from padre import channel as c
from padre import date_utils as du
from padre import event
from padre import exceptions as excp
from padre import google_calendar
from padre import handler_utils as hu
from padre import ldap_utils
from padre import maintenance_utils as mau
from padre import message as m
from padre import periodics
from padre import utils

from padre.handlers import jenkins as jenkins_handlers

from padre.watchers import gerrit as gerrit_watcher
from padre.watchers import slack as slack_watcher
from padre.watchers import telnet as telnet_watcher

from padre.wsgi_servers import github as github_server
from padre.wsgi_servers import jira as jira_server
from padre.wsgi_servers import sensu as sensu_server
from padre.wsgi_servers import status as status_server

from padre.senders import slack as slack_sender

LOG = logging.getLogger(__name__)
SUGGESTABLE_KINDS = ['slack', 'telnet']
PRE_PROCESSABLE_KINDS = ['slack', 'telnet']
HELLOS = [
    "Hello", "Good day", "Howdy",
]
BIRTH_TEMPLATES = [
    "%(hello)s, I live! (getting closer to self-realization :robotdevil:)",
]


def _modified_listener(scheduler, event):
    job_id = event.job_id
    job = scheduler.get_job(job_id, jobstore=event.jobstore)
    if job is None:
        job_name = "???"
    else:
        job_name = job.name.splitlines()[0]
    LOG.debug("Job '%s' [%s] has been modified", job_id, job_name)


def _submitted_listener(scheduler, event):
    job_id = event.job_id
    job = scheduler.get_job(job_id, jobstore=event.jobstore)
    if job is None:
        job_name = "???"
    else:
        job_name = job.name.splitlines()[0]
    LOG.debug("Job '%s' [%s] has been submitted, hopefully it runs soon",
              job_id, job_name)


def _done_listener(scheduler, event):
    job_id = event.job_id
    job = scheduler.get_job(job_id, jobstore=event.jobstore)
    if job is None:
        job_name = "???"
        job_next = None
    else:
        job_name = job.name.splitlines()[0]
        now = du.get_now(tz=scheduler.timezone)
        job_next_diff = job.next_run_time - now
        job_next = utils.format_seconds(job_next_diff.total_seconds())
    if event.exception is not None:
        LOG.error("Failed run of job '%s' [%s]", job_id, job_name,
                  exc_info=True)
    else:
        LOG.debug("Happily ran job '%s' [%s]", job_id, job_name)
    if job_next is not None:
        LOG.debug("Job '%s' [%s] will"
                  " run again in %s", job_id, job_name, job_next)


def _fetch_snow_client(config, secrets):
    try:
        snow_acct = secrets.ci['SNOW']['SNOW API service account']
        snow_user = snow_acct.username
        snow_user_pass = snow_acct.password
        snow_env = config.snow.environment
    except (AttributeError, KeyError):
        return None
    else:
        try:
            snow_timeout = config.snow["timeout"]
        except (AttributeError, KeyError):
            snow_timeout = None
        return mau.ServiceNow(snow_env, snow_user, snow_user_pass,
                              timeout=snow_timeout)


def _fetch_gerrit_mqtt_client(config, secrets):
    try:
        mqtt_config = config.gerrit.mqtt
    except AttributeError:
        return None
    else:
        return gerrit_watcher.MQTTClient(mqtt_config)


def _fetch_ldap_client(config, secrets):
    ldap_config = {}
    try:
        # These are **not** optional.
        for k in ('uri', 'bind_dn', 'bind_password',
                  'user_dn', 'service_user_dn', 'group_dn'):
            ldap_config[k] = config.ldap[k]
        # These are optional.
        for k in ('cache_size', 'cache_ttl'):
            try:
                ldap_config[k] = config.ldap[k]
            except (AttributeError, KeyError):
                pass
    except (AttributeError, KeyError):
        return None
    else:
        return ldap_utils.LdapClient(**ldap_config)


def _fetch_slack_client(config, secrets):
    try:
        slack_token = config.slack.token
        slack_token = slack_token.strip()
    except AttributeError:
        return None
    else:
        if not slack_token:
            return None
        return slackclient.SlackClient(slack_token)


def _fetch_jenkins_client(config, secrets):
    try:
        jenkins_config = config.jenkins
        jenkins_user = jenkins_config.user
        jenkins_url = jenkins_config.url
        jenkins_token = jenkins_config.token
    except AttributeError:
        return None
    else:
        return tj.Jenkins(jenkins_url, jenkins_user, jenkins_token,
                          timeout=jenkins_config.get("timeout"),
                          max_retries=jenkins_config.get('max_retries'))


def _fetch_github_client(config, secrets):
    try:
        github_config = config.github
        github_user = github_config.user
        github_password = github_config.password
        github_base_url = github_config.base_url
    except AttributeError:
        return None
    else:
        return github.Github(github_user, github_password,
                             base_url=github_base_url,
                             timeout=github_config.get("timeout"))


def _fetch_jira_client(config, secrets):
    try:
        jira_config = config.jira
        jira_user = jira_config.user
        jira_password = jira_config.password
        jira_base_url = jira_config.urls.base
    except AttributeError:
        return None
    else:
        return jiraclient.JIRA(jira_base_url,
                               basic_auth=(jira_user, jira_password),
                               timeout=jira_config.get("timeout"))


def _fetch_elastic_client(config, secrets):
    try:
        elastic_config = config.elastic
        elastic_endpoint = elastic_config.endpoint
        elastic_host = elastic_endpoint.host
        elastic_user = elastic_endpoint.user
        elastic_password = elastic_endpoint.password
    except AttributeError:
        return None
    else:
        try:
            elastic_host += ":%s" % elastic_endpoint.port
        except AttributeError:
            pass
        return elasticsearch.Elasticsearch(
            hosts=[elastic_host],
            use_ssl=elastic_endpoint.get("ssl", True),
            http_auth=(elastic_user, elastic_password),
            timeout=elastic_endpoint.get("timeout"),
            # TODO: Turn this on at some point... once we figure out
            # what the needed root certs are (because certifi is already
            # installed).
            verify_certs=False)


def _rank_prefixed_suffixed(trigger_text, message_text):
    if (trigger_text.startswith(message_text) or
            message_text.startswith(trigger_text) or
            trigger_text.endswith(message_text) or
            message_text.endswith(trigger_text)):
        return 1
    return 0


def _find_suggestion(handlers, message_text, default_suggestion=''):
    def _clean_text(text):
        text = text.lower()
        text = re.sub(r"\s+", " ", text)
        text = text.strip()
        return text
    message_text = _clean_text(message_text)
    if not message_text or not handlers:
        return default_suggestion
    triggers = []
    for h_cls in handlers:
        for h_cls_trigger in h_cls.handles_what.get('triggers', []):
            h_cls_trigger_text = _clean_text(h_cls_trigger.text)
            if h_cls_trigger_text:
                triggers.append((h_cls_trigger, h_cls_trigger_text))
    if not triggers:
        return default_suggestion
    rankings = []
    for t, t_text in triggers:
        t_edit_dist = distance.levenshtein(
            t_text, message_text,
            max_dist=min(len(message_text), len(t_text)))
        if t_edit_dist >= 0:
            rankings.append((t, t_text, t_edit_dist))
    suggestion = None
    if rankings:
        # TODO: maybe just keep track of the min ones and then
        # avoid this sort + selection... in the first place???
        best_rankings = []
        for t, t_text, t_edit_dist in sorted(rankings, key=lambda v: v[2]):
            if not best_rankings:
                best_rankings.append((t, t_text, t_edit_dist))
            else:
                _t2, _t2_text, t2_edit_dist = best_rankings[-1]
                if t2_edit_dist != t_edit_dist:
                    break
                else:
                    best_rankings.append((t, t_text, t_edit_dist))
        if len(best_rankings) == 1:
            suggestion = best_rankings[0][0].text
        else:
            # Try to find one that starts with the same prefix or ends
            # with the same suffix; and prefer those...
            rankings = []
            for t, t_text, _t_edit_dist in best_rankings:
                rankings.append((t, t_text,
                                 _rank_prefixed_suffixed(t_text,
                                                         message_text)))
            best_rankings = sorted(rankings, key=lambda v: v[2],
                                   reverse=True)
            suggestion = best_rankings[0][0].text
    if suggestion is None:
        suggestion = default_suggestion
    return suggestion


def _make_birth_message():
    all_hellos = list(HELLOS)
    birth_tpl = random.choice(BIRTH_TEMPLATES)
    return birth_tpl % {'hello': random.choice(all_hellos)}


class Bot(object):
    idle_wait = 1.0

    def __init__(self, config, secrets):
        self.config = config
        self.secrets = secrets
        self.clients = munch.Munch()
        self.watchers = munch.Munch()
        self.calendars = munch.Munch()
        self.wsgi_servers = munch.Munch()
        self.active_handlers = set()
        self.dead = event.Event()
        self.locks = munch.Munch({
            # Used for any interaction with the bots brain to ensure
            # that it isn't being mutated by many threads at the same
            # time.
            'brain': threading.Lock(),
            # Used for any interaction with the channel statistics;
            # to ensure that multiple threads aren't messing with it
            # at the same time (so that we get accurate counts).
            'channel_stats': threading.Lock(),
            'prior_handlers': threading.Lock(),
        })
        self.topo_loader = None
        self.date_wrangler = du.DateWrangler(default_tz=config.get("tz"))
        self.executors = {}
        self.handlers = []
        self.started_at = None
        self.scheduler = None
        self.slack_sender = None
        self.channel_stats = {
            c.BROADCAST: {},
            c.TARGETED: {},
            c.FOLLOWUP: {},
        }
        self.prior_handlers = {
            c.BROADCAST: {},
            c.TARGETED: {},
            c.FOLLOWUP: {},
        }
        self.sent_birth_message = False
        self.quiescing = False
        self.brain = None

    @property
    def hostname(self):
        my_hostname = self.config.get('hostname')
        if not my_hostname:
            try:
                my_hostname = socket.gethostname()
            except socket.error:
                pass
            if not my_hostname:
                # NOTE: This will always return something...
                my_hostname = netutils.get_my_ipv4()
        return my_hostname

    @property
    def name(self):
        bot_name = self.config.get("name")
        if not bot_name:
            bot_name = os.environ.get("BOT")
        return bot_name

    def _insert_periodics(self, scheduler):
        try:
            danger_period = self.config.danger_period
        except AttributeError:
            pass
        else:
            runner = periodics.DangerZoneDetector(self)
            if runner.is_enabled(self):
                runner_name = reflection.get_class_name(runner)
                runner_description = periodics.DangerZoneDetector.__doc__
                runner_trigger = cron.CronTrigger.from_crontab(
                    danger_period, timezone=self.config.tz)
                runner_id = utils.hash_pieces([
                    runner_name, danger_period, runner_description,
                ], max_len=8)
                scheduler.add_job(
                    runner, trigger=runner_trigger,
                    jobstore='memory',
                    name="\n".join([runner_name, runner_description]),
                    id=runner_id, coalesce=True)

    def _build_scheduler(self, default_max_workers):
        jobstores = {
            'memory': MemoryJobStore(),
        }
        jobstores['default'] = jobstores['memory']
        try:
            jobstores['sqlalchemy'] = SQLAlchemyJobStore(
                url=self.config.scheduler.db_uri)
        except AttributeError:
            pass
        executors = {}
        try:
            executors['default'] = ThreadPoolExecutor(
                max_workers=self.config.scheduler.max_workers)
        except AttributeError:
            executors['default'] = ThreadPoolExecutor(
                max_workers=default_max_workers)
        sched = BackgroundScheduler(jobstores=jobstores,
                                    executors=executors,
                                    tz=pytz.timezone(self.config.tz))
        sched.add_listener(functools.partial(_done_listener, sched),
                           events.EVENT_JOB_EXECUTED | events.EVENT_JOB_ERROR)
        sched.add_listener(functools.partial(_submitted_listener, sched),
                           events.EVENT_JOB_SUBMITTED)
        sched.add_listener(functools.partial(_modified_listener, sched),
                           events.EVENT_JOB_MODIFIED)
        return sched

    def _shutdown(self):
        print("Shutting down...")
        if self.watchers:
            LOG.info("Stopping %s watchers", len(self.watchers))
            for w_name, w in self.watchers.items():
                LOG.debug(" - %s", w_name)
                w.dead.set()
                if w.is_alive():
                    w.join()
            self.watchers.clear()
        if self.wsgi_servers:
            LOG.info("Stopping %s wsgi mini-servers", len(self.wsgi_servers))
            for w_name, w in self.wsgi_servers.items():
                LOG.debug(" - %s", w_name)
                w.shutdown()
                if w.is_alive():
                    w.join()
            self.wsgi_servers.clear()
        if self.scheduler is not None:
            LOG.info("Stopping periodic scheduler")
            try:
                self.scheduler.shutdown(wait=True)
            except schedulers.SchedulerNotRunningError:
                pass
            self.scheduler = None
        for k in sorted(six.iterkeys(self.executors)):
            executor = self.executors[k]
            try:
                LOG.info("Waiting for (up to) %s worker threads"
                         " to FINISH (they process %s messages)",
                         executor.max_workers, k)
            except AttributeError:
                LOG.info("Waiting for (up to) ?? worker threads"
                         " to FINISH (they process %s messages)", k)
            executor.shutdown()
            del self.executors[k]
        if self.brain is not None:
            LOG.info("Syncing and closing brain")
            self.brain.sync()
            self.brain.close()
            self.brain = None
        print("Goodbye :)")

    def submit_message(self, message, desired_channel, executor=None):
        if desired_channel == c.BROADCAST:
            processing_func = self._process_broadcast_message
        elif desired_channel == c.FOLLOWUP:
            processing_func = self._process_followup_messsage
        elif desired_channel == c.TARGETED:
            processing_func = self._process_targeted_message
        else:
            raise ValueError("Unable to submit message %s"
                             " to unknown channel '%s'" % (message,
                                                           desired_channel))
        if executor is None:
            if desired_channel == c.FOLLOWUP:
                # These need to run on their own thread pool since it is
                # quite possible (and expected) that threads on the other pool
                # are blocking/waiting for some followup message to come in to
                # unblock them; so being that is the case, we can't run these
                # followups on the same pool (because they may never run if
                # that pool is back logged).
                executor = self.executors['followups']
            else:
                executor = self.executors['primary']
        if message.kind in PRE_PROCESSABLE_KINDS:
            message = self._preprocess(message)
        fut = executor.submit(processing_func, desired_channel, message)
        fut.message = message
        return fut

    def _capture_occurrence(self, channel, message):
        target_channel_stats = self.channel_stats[channel]
        with self.locks.channel_stats:
            try:
                root_stats = target_channel_stats[message.kind]
            except KeyError:
                target_channel_stats[message.kind] = {}
                root_stats = target_channel_stats[message.kind]
            try:
                root_stats[message.sub_kind] += 1
            except KeyError:
                root_stats[message.sub_kind] = 1

    def _process_broadcast_message(self, channel, message):
        if self.dead.is_set() or self.quiescing:
            raise excp.Dying
        LOG.debug("Processing %s message: %s", channel.name.lower(), message)
        self._capture_occurrence(channel, message)
        for h_cls in list(self.handlers):
            if self.dead.is_set():
                raise excp.Dying
            h_match = h_cls.handles(message, channel,
                                    h_cls.fetch_config(self))
            if not h_match:
                continue
            h = h_cls(self, message)
            with self._capture_for_record(channel, message, h):
                h_cls_stats = h_cls.stats
                h_cls_stats.ran += 1
                try:
                    h.run(h_match)
                except Exception:
                    LOG.exception(
                        "Processing %s with '%s' failed", message,
                        reflection.get_class_name(h_cls))
                    h_cls_stats.failed += 1
                    try:
                        h_cls_stats.total_run_time += h.watch.elapsed()
                    except RuntimeError:
                        pass
                else:
                    try:
                        h_cls_stats.total_run_time += h.watch.elapsed()
                    except RuntimeError:
                        pass

    @contextlib.contextmanager
    def _capture_for_record(self, channel, message, handler):
        self.active_handlers.add(handler)
        try:
            yield handler
        finally:
            self.active_handlers.discard(handler)
            with self.locks.prior_handlers:
                ch_prior_handlers = self.prior_handlers[channel]
                try:
                    k_ch_prior_handlers = ch_prior_handlers[message.kind]
                except KeyError:
                    try:
                        max_historys = dict(self.config.max_history)
                    except AttributeError:
                        max_historys = {}
                    try:
                        k_max_history = max_historys[message.kind]
                    except KeyError:
                        k_max_history = 0
                    k_ch_prior_handlers = collections.deque(
                        maxlen=max(0, k_max_history))
                    k_ch_prior_handlers.appendleft(handler)
                    ch_prior_handlers[message.kind] = k_ch_prior_handlers
                else:
                    k_ch_prior_handlers.appendleft(handler)

    def _process_followup_messsage(self, channel, message):
        if self.dead.is_set() or self.quiescing:
            raise excp.Dying
        LOG.debug("Processing %s message: %s", channel.name.lower(), message)
        self._capture_occurrence(channel, message)
        handled = False
        message_thread_ts = message.body.get("thread_ts")
        if message_thread_ts:
            handler = None
            for h in list(self.active_handlers):
                if message_thread_ts == h.message.body.get("ts"):
                    handler = h
                    break
            if handler is not None:
                handler_followers = list(handler.followers)
                if handler_followers:
                    handled = True
                    for handler_follower in handler_followers:
                        if handler_follower(handler, message):
                            break
        if not handled:
            raise excp.NoFollowupHandlerFound(message=message)

    def _preprocess(self, message):
        from_who = message.body.get("user_id")
        if from_who:
            from_who = "user:%s" % from_who
            try:
                with self.locks.brain:
                    text_aliases = dict(self.brain[from_who]['aliases'])
            except KeyError:
                pass
            else:
                message = message.rewrite(text_aliases=text_aliases)
        return message

    def _process_targeted_message(self, channel, message):
        if self.dead.is_set() or self.quiescing:
            raise excp.Dying
        LOG.debug("Processing %s message: %s", channel.name.lower(), message)
        self._capture_occurrence(channel, message)
        for h_cls in list(self.handlers):
            h_match = h_cls.handles(message, channel,
                                    h_cls.fetch_config(self))
            if not h_match:
                continue
            h = h_cls(self, message)
            with self._capture_for_record(channel, message, h):
                h_cls_stats = h_cls.stats
                h_cls_stats.ran += 1
                try:
                    result = h.run(h_match)
                except Exception:
                    with excutils.save_and_reraise_exception():
                        h_cls_stats.failed += 1
                        try:
                            h_cls_stats.total_run_time += h.watch.elapsed()
                        except RuntimeError:
                            pass
                else:
                    try:
                        h_cls_stats.total_run_time += h.watch.elapsed()
                    except RuntimeError:
                        pass
                    return result
        if message.headers.get(m.TO_ME_HEADER, False):
            if message.kind in SUGGESTABLE_KINDS:
                suggestion = _find_suggestion(self.handlers,
                                              message.body.text)
            else:
                suggestion = ''
            raise excp.NoHandlerFound(message=message,
                                      suggestion=suggestion)

    def run(self):
        print("Starting up...")
        self.dead.clear()
        self.quiescing = False
        for v in self.prior_handlers.values():
            v.clear()
        for v in self.channel_stats.values():
            v.clear()
        self.watchers.clear()
        self.clients.clear()
        self.handlers = []
        self.executors.clear()
        self.active_handlers.clear()
        self.calendars.clear()
        self.sent_birth_message = False

        brain_path = os.path.join(
            self.config.persistent_working_dir, 'brain.sqlite')
        LOG.info("Opening (or creating) brain at '%s'", brain_path)
        self.brain = sqlitedict.SqliteDict(
            filename=brain_path, tablename='padre',
            autocommit=True, flag='c',
            encode=mu.dumps, decode=mu.loads)

        LOG.info("Building calendars")
        try:
            all_calendars = self.config.calendars
        except AttributeError:
            pass
        else:
            for calendar_name, calendar_conf in all_calendars.items():
                self.calendars[calendar_name] = google_calendar.Calendar(
                    calendar_conf, auto_setup=True)

        LOG.info("Building (cloud) topology loader")
        try:
            topo_cls = self.config.plugins.topo_loader_class
        except AttributeError:
            topo_cls = None
        if topo_cls:
            self.topo_loader = importutils.import_object(
                topo_cls, self.config, secrets=self.secrets)
        else:
            self.topo_loader = None

        LOG.info("Building clients")
        tmp_clients = {
            'github_client': _fetch_github_client(self.config, self.secrets),
            'ldap_client': _fetch_ldap_client(self.config, self.secrets),
            'jenkins_client': _fetch_jenkins_client(self.config, self.secrets),
            'slack_client': _fetch_slack_client(self.config, self.secrets),
            'jira_client': _fetch_jira_client(self.config, self.secrets),
            'elastic_client': _fetch_elastic_client(self.config, self.secrets),
            'gerrit_mqtt_client': _fetch_gerrit_mqtt_client(self.config,
                                                            self.secrets),
            'snow_client': _fetch_snow_client(self.config, self.secrets),
        }
        try:
            client_builder_func = self.config.client_builder_func
        except AttributeError:
            pass
        else:
            if client_builder_func:
                LOG.info("Building externally provided clients")
                client_builder_func = utils.import_func(client_builder_func)
                ext_tmp_clients = client_builder_func(self.config,
                                                      self.secrets)
                for client_name, client in ext_tmp_clients.items():
                    if client is None:
                        continue
                    else:
                        LOG.debug("Including externally provided"
                                  " '%s' client", client_name)
                        tmp_clients[client_name] = client
        for client_name, client in tmp_clients.items():
            if client is not None:
                self.clients[client_name] = client
            else:
                self.clients.pop(client_name, None)

        if 'slack_client' in self.clients:
            self.slack_sender = slack_sender.Sender(self)
        else:
            self.slack_sender = None

        def on_slack_disconnected():
            LOG.warning("Lost connection to slack.", exc_info=True)

        def on_slack_connected(slack_login_data):
            LOG.info(
                "Connected to slack at domain '%s' with user '%s' with"
                " user id '%s'", slack_login_data['team']['domain'],
                slack_login_data['self']['name'],
                slack_login_data['self']['id'])
            admin_channel = self.config.get("admin_channel")
            if not self.sent_birth_message and admin_channel:
                LOG.info("Emitting birth message to "
                         "'%s' channel", admin_channel)
                self.sent_birth_message = True
                try:
                    me = pkg_resources.get_distribution('padre')
                    attachment = {
                        'pretext': _make_birth_message(),
                        'mrkdwn_in': ['pretext'],
                        'fields': [
                            {
                                'title': 'Version',
                                'value': str(me.version),
                                'short': True,
                            },
                        ],
                    }
                    self.slack_sender.post_send(attachments=[attachment],
                                                channel=admin_channel,
                                                as_user=True)
                except Exception:
                    LOG.warning("Failed emitting birth message", exc_info=True)

        LOG.info("Building watchers")
        if 'slack_client' in self.clients:
            self.watchers['slack'] = slack_watcher.Watcher(
                self, on_connected=on_slack_connected,
                on_disconnected=on_slack_disconnected)
        else:
            self.watchers.pop("slack", None)
        if 'gerrit_mqtt_client' in self.clients:
            self.watchers['gerrit'] = gerrit_watcher.Watcher(self)
        else:
            self.watchers.pop("gerrit", None)

        try:
            telnet_conf = self.config.telnet
        except AttributeError:
            self.watchers.pop("telnet", None)
        else:
            self.watchers.update({
                'telnet': telnet_watcher.Watcher(self, telnet_conf),
            })

        LOG.info("Building wsgi mini-servers")
        try:
            max_wsgi_workers = max(1, self.config.max_wsgi_workers)
        except AttributeError:
            max_wsgi_workers = 1
        for server_name, func in [("sensu", sensu_server.create_server),
                                  ("github", github_server.create_server),
                                  ("jira", jira_server.create_server),
                                  ("status", status_server.create_server)]:
            try:
                wsgi_server = func(self, max_wsgi_workers)
            except AttributeError:
                self.wsgi_servers.pop(server_name, None)
            else:
                self.wsgi_servers[server_name] = wsgi_server

        LOG.info("Starting up executors")
        executors = {}
        executors_workers = {}
        try:
            tmp_max_workers = max(1, self.config.max_workers)
            executors_workers['primary'] = int(tmp_max_workers)
        except AttributeError:
            executors_workers['primary'] = 1
        executors_workers['followups'] = executors_workers['primary']
        for k in ['primary', 'followups']:
            tmp_max_workers = executors_workers[k]
            try:
                executor = futurist.ThreadPoolExecutor(tmp_max_workers)
                executor.max_workers = tmp_max_workers
            except Exception:
                with excutils.save_and_reraise_exception():
                    self._shutdown()
            else:
                executors[k] = executor
        self.executors.update(executors)

        maybe_handlers = []
        LOG.info("Finding configuration specified handlers")
        try_find_handlers = []
        try:
            try_find_handlers.extend(self.config.plugins.get("handlers", []))
        except AttributeError:
            pass
        try:
            for handler in try_find_handlers:
                if isinstance(handler, dict):
                    # Extract all the handlers defined in that module.
                    maybe_handlers.extend(
                        hu.get_handlers(handler['module'],
                                        recurse=handler.get("recurse", False)))
                elif isinstance(handler, six.string_types):
                    # Extract just one.
                    handler_cls = hu.get_handler(handler)
                    if handler_cls is not None:
                        maybe_handlers.append(handler_cls)
                else:
                    raise RuntimeError("Unknown handler found: %s" % handler)
        except Exception:
            with excutils.save_and_reraise_exception():
                self._shutdown()

        LOG.info("Finding procedurally generated slack handlers")
        if 'jenkins_client' in self.clients:
            try:
                jenkins_jobs = dict(self.config.jenkins.jobs)
            except AttributeError:
                jenkins_jobs = {}
            if jenkins_jobs:
                # NOTE: It doesn't really matter which executor we use, any
                # will do for temporary usage here... (to speed up the
                # time it takes to talk with jenkins...)
                maybe_handlers.extend(
                    jenkins_handlers.load_jenkins_handlers(
                        jenkins_jobs, self.clients.jenkins_client,
                        executors['primary'], log=LOG))

        enabled_handlers = []
        disabled_handlers = []
        LOG.info("Setting up %s built-in & generated handlers",
                 len(maybe_handlers))
        try:
            for h_cls in maybe_handlers:
                h_cls.setup_class(self)
                if h_cls.is_enabled(self):
                    enabled_handlers.append(h_cls)
                else:
                    disabled_handlers.append(h_cls)
        except Exception:
            with excutils.save_and_reraise_exception():
                self._shutdown()

        LOG.info("Ordering/sorting %s enabled"
                 " handlers", len(enabled_handlers))
        try:
            handlers = hu.sort_handlers(enabled_handlers)
        except Exception:
            with excutils.save_and_reraise_exception():
                self._shutdown()
        else:
            self.handlers = handlers

        LOG.info("Enabled %s handlers", len(self.handlers))
        if LOG.isEnabledFor(logging.DEBUG):
            for h_cls in self.handlers:
                LOG.debug(" - %s", reflection.get_class_name(h_cls))
        LOG.info("Disabled %s handlers", len(disabled_handlers))
        if LOG.isEnabledFor(logging.DEBUG):
            for h_cls in disabled_handlers:
                LOG.debug(" - %s", reflection.get_class_name(h_cls))

        LOG.info("Building a periodic scheduler")
        try:
            self.scheduler = self._build_scheduler(
                executors_workers['primary'])
        except Exception:
            with excutils.save_and_reraise_exception():
                self._shutdown()

        try:
            LOG.info("Setting up & starting %s watchers", len(self.watchers))
            for w_name, w in self.watchers.items():
                LOG.debug(" - %s", w_name)
                w.setup()
                w.start()
        except Exception:
            with excutils.save_and_reraise_exception():
                self._shutdown()

        LOG.info("Setting up periodic scheduler")
        try:
            self._insert_periodics(self.scheduler)
            for h_cls in self.handlers:
                h_cls.insert_periodics(self, self.scheduler)
            for w in self.watchers.values():
                w.insert_periodics(self, self.scheduler)
        except Exception:
            with excutils.save_and_reraise_exception():
                self._shutdown()

        try:
            LOG.info("Setting up & starting %s wsgi"
                     " mini-servers", len(self.wsgi_servers))
            for w_name, w in self.wsgi_servers.items():
                LOG.debug(" - %s", w_name)
                w.setup()
                w.start()
        except Exception as exc:
            LOG.critical("Got an %s exception when setup wsgi servers",
                         type(exc).__name__)
            with excutils.save_and_reraise_exception():
                self._shutdown()

        initial_jobs = self.scheduler.get_jobs()
        LOG.info("Starting periodic scheduler (with %s initial"
                 " jobs)", len(initial_jobs))
        if initial_jobs:
            for job in initial_jobs:
                LOG.debug(" - %s (trigger=%s)", job.name.splitlines()[0],
                          job.trigger)
        try:
            self.scheduler.start()
        except Exception:
            with excutils.save_and_reraise_exception():
                self._shutdown()

        if self.slack_sender is not None:
            LOG.info("Setting up slack sender")
            try:
                self.slack_sender.setup()
            except Exception:
                with excutils.save_and_reraise_exception():
                    self._shutdown()

        print("Main thread idling...")
        self.started_at = self.date_wrangler.get_now()
        try:
            while not self.dead.is_set():
                self.dead.wait(self.idle_wait)
        except Exception:
            with excutils.save_and_reraise_exception():
                self._shutdown()
        else:
            self._shutdown()
            if self.dead.value == event.Event.DIE:
                return False
            else:
                return True
        finally:
            self.started_at = None
