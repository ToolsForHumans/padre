# Taken from https://github.com/harlowja/gerritbot2/ and slightly adjusted
# to work *without* errbot in our codebase here.

from datetime import datetime

import json
import logging
import threading

from oslo_utils import timeutils
import paho.mqtt.client as mqtt

from padre import channel as c
from padre import finishers
from padre import message
from padre import utils

import munch
import six

LOG = logging.getLogger(__name__)


class MQTTClient(object):
    """Client that better handles the underlying client crapping out."""

    MAX_READ_LOOP_DURATION = 1.0
    RECONNECT_WAIT = 1.0

    def __init__(self, config):
        self.config = config

    def run(self, death, translator_func, submit_func):

        def on_message(client, userdata, msg):
            if not msg.topic or not msg.payload:
                return
            try:
                payload = msg.payload
                if isinstance(payload, six.binary_type):
                    payload = payload.decode("utf8")
                details = {'event': json.loads(payload)}
            except (UnicodeError, ValueError):
                LOG.exception(
                    "Received corrupted/invalid payload: %s", msg.payload)
            else:
                message = translator_func(details)
                if message is not None:
                    try:
                        submit_func(message)
                    except RuntimeError:
                        pass

        config = self.config
        real_client = utils.make_mqtt_client(config)
        real_client.on_message = on_message
        rc = mqtt.MQTT_ERR_SUCCESS
        running = True

        while not death.is_set() and running:
            max_duration = self.MAX_READ_LOOP_DURATION
            reconnect_wait = self.RECONNECT_WAIT
            with timeutils.StopWatch(duration=max_duration) as watch:
                try:
                    while (rc == mqtt.MQTT_ERR_SUCCESS and
                           not watch.expired()):
                        rc = real_client.loop(timeout=watch.leftover())
                        if death.is_set():
                            break
                except IOError:
                    LOG.exception("Failed consumption")
                    rc = mqtt.MQTT_ERR_UNKNOWN
                if rc in [mqtt.MQTT_ERR_NO_CONN,
                          mqtt.MQTT_ERR_CONN_REFUSED,
                          mqtt.MQTT_ERR_CONN_LOST,
                          mqtt.MQTT_ERR_NOT_FOUND,
                          mqtt.MQTT_ERR_UNKNOWN]:
                    LOG.warn("Reconnecting, reason=%s",
                             mqtt.error_string(rc))
                    try:
                        real_client.reconnect()
                    except IOError:
                        LOG.exception("Failed reconnecting")
                        LOG.info("Waiting %s seconds before retrying",
                                 reconnect_wait)
                        death.wait(reconnect_wait)
                    else:
                        rc = mqtt.MQTT_ERR_SUCCESS
                elif rc == mqtt.MQTT_ERR_NOMEM:
                    # The client seems to leak memory...
                    #
                    # What a PITA...
                    LOG.critical("Regenerating client, client"
                                 " reported out of memory")
                    try:
                        real_client = utils.make_mqtt_client(config)
                    except IOError:
                        LOG.critical("Fatal client failure (unable"
                                     " to recreate client), reason=%s",
                                     mqtt.error_string(rc))
                        running = False
                    else:
                        real_client.on_message = on_message
                        rc = mqtt.MQTT_ERR_SUCCESS
                elif rc != mqtt.MQTT_ERR_SUCCESS:
                    LOG.critical("Fatal client failure, reason=%s",
                                 mqtt.error_string(rc))
                    running = False


def extract_entity(data):
    return munch.Munch({
        'username': data['username'],
        'name': data['name'],
        'email': data.get('email'),
    })


def extract_patch_set(data):
    return munch.Munch({
        'kind': data['kind'],
        'author': extract_entity(data['author']),
        'inserts': int(data['sizeInsertions']),
        'deletes': int(data['sizeDeletions']),
        'uploader': extract_entity(data['uploader']),
        'revision': data['revision'],
        'created_on': datetime.fromtimestamp(data['createdOn']),
    })


def extract_change(data):
    return munch.Munch({
        'status': data['status'],
        'commit_message': data['commitMessage'],
        'number': int(data['number']),
        'url': data['url'],
        'project': data['project'],
        'owner': extract_entity(data['owner']),
        'subject': data['subject'],
        'id': data['id'],
        'topic': data.get("topic"),
        'branch': data['branch'],
    })


def extract_patch_set_created(data):
    return munch.Munch({
        'patch_set': extract_patch_set(data['patchSet']),
        'change': extract_change(data['change']),
        'uploader': extract_entity(data['uploader']),
        'created_on': datetime.fromtimestamp(data['eventCreatedOn']),
    })


class Watcher(threading.Thread):
    GERRIT_EVENT_TO_EXTRACTOR = {
        'change-abandoned': None,
        'change-merged': None,
        'change-restored': None,
        'comment-added': None,
        'draft-published': None,
        'merge-failed': None,
        'patchset-created': extract_patch_set_created,
        'patchset-notified': None,
        'project-created': None,
        'ref-replicated': None,
        'ref-replication-done': None,
        'ref-updated': None,
        'reviewer-added': None,
        'topic-changed': None,
    }

    def __init__(self, bot):
        super(Watcher, self).__init__()
        self.dead = threading.Event()
        self.bot = bot
        self.daemon = True

    def setup(self):
        pass

    @staticmethod
    def insert_periodics(bot, scheduler):
        pass

    def run(self):

        def translate_event(details):
            try:
                event_type = details['event'].pop('type')
            except KeyError:
                return None
            extract_func = self.GERRIT_EVENT_TO_EXTRACTOR.get(event_type)
            if not extract_func:
                return None
            try:
                event = extract_func(details['event'])
            except (KeyError, TypeError, ValueError):
                LOG.exception(
                    "Received unexpected payload: %s", details['event'])
                return None
            else:
                m_headers = {
                    message.VALIDATED_HEADER: False,
                    message.TO_ME_HEADER: True,
                    message.CHECK_AUTH_HEADER: False,
                }
                m_body = event
                m_kind = 'gerrit/%s' % event_type
                m = message.Message(m_kind, m_headers, m_body)
                return m

        def submit_message(message):
            self.bot.submit_message(message, c.BROADCAST)
            fut = self.bot.submit_message(message, c.TARGETED)
            fut.add_done_callback(
                finishers.log_on_fail(self.bot, message, log=LOG))

        mqtt_client = self.bot.clients.gerrit_mqtt_client
        mqtt_client.run(self.dead, translate_event, submit_message)
