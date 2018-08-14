import logging
import traceback

from padre import slack_utils as su


class SlackLoggerAdapter(object):
    """Adapter around a logger to also send those logs to slack."""

    def __init__(self, logger,
                 slack_sender=None, ignore_levels=False,
                 channel=None, attachment_addons=None,
                 threaded=False, thread_ts=None):
        self.slack_sender = slack_sender
        self.ignore_levels = ignore_levels
        self.channel = channel
        self.attachment_addons = attachment_addons
        self.threaded = threaded
        self.logger = logger
        self.thread_ts = thread_ts

    def isEnabledFor(self, level):
        return self.logger.isEnabledFor(level)

    def error(self, msg, *args, **kwargs):
        self.log(logging.ERROR, msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        kwargs['exc_info'] = 1
        self.log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self.log(logging.CRITICAL, msg, *args, **kwargs)

    fatal = critical

    def warn(self, msg, *args, **kwargs):
        self.log(logging.WARN, msg, *args, **kwargs)

    warning = warn

    def info(self, msg, *args, **kwargs):
        self.log(logging.INFO, msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        self.log(logging.DEBUG, msg, *args, **kwargs)

    def log(self, level, msg, *args, **kwargs):
        text = kwargs.pop("text", '')
        max_attempts = min(1, kwargs.pop('max_attempts', 1))
        to_slack = kwargs.pop('slack', True)
        self.logger.log(level, msg, *args, **kwargs)
        if ((self.ignore_levels or self.isEnabledFor(level)) and
                (to_slack and self.slack_sender and self.channel)):
            if args:
                real_message = msg % args
            else:
                real_message = msg
            tb_text = ''
            if kwargs.get("exc_info"):
                tb_text = traceback.format_exc()
            attachment = {
                'fallback': real_message,
                'pretext': real_message,
                'mrkdwn_in': [],
            }
            if self.attachment_addons:
                attachment.update(self.attachment_addons)
            if tb_text:
                if text:
                    text += "\n"
                text += "```\n"
                text += tb_text
                if not tb_text.endswith("\n"):
                    text += "\n"
                text += "```\n"
                attachment['mrkdwn_in'].append("text")
            if text:
                attachment['text'] = text
            message_color = su.LOG_COLORS.get(level)
            if message_color:
                attachment['color'] = message_color
            if self.threaded and self.thread_ts is not None:
                ts = self.thread_ts
            else:
                ts = None
            try:
                resp = self.slack_sender.post_send(
                    attachments=[attachment],
                    channel=self.channel,
                    text=' ', link_names=True,
                    as_user=True, unfurl_links=False,
                    max_attempts=max_attempts,
                    log=self.logger, thread_ts=ts)
            except Exception:
                pass
            else:
                if self.thread_ts is None and self.threaded:
                    self.thread_ts = resp.get('ts')
