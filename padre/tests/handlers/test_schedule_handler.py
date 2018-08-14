from datetime import datetime
import time

import mock
import pytz
from testtools import TestCase

from padre import channel as c
from padre import exceptions as excp
from padre import handler
from padre.handlers import schedule
from padre.tests import common


class ResumeHandlerTest(TestCase):
    ZERO_DT = datetime.fromtimestamp(0, pytz.utc)

    def test_expected_handled(self):
        bot = common.make_bot()

        m = common.make_message(text="periodics resume 1", to_me=True)
        self.assertTrue(
            schedule.ResumeHandler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="do something else", to_me=True)
        self.assertEqual(
            schedule.ResumeHandler.handles(m, c.TARGETED, bot.config), None)

    def test_not_found(self):
        bot = common.make_bot()

        jobs = {}
        bot.scheduler.get_job.side_effect = lambda job_id: jobs.get(job_id)

        m = common.make_message(text="periodics resume 1",
                                to_me=True, user_id="me")

        h = schedule.ResumeHandler(bot, m)
        self.assertRaises(excp.NotFound, h.run, handler.HandlerMatch("1"))

    def test_resumed(self):
        bot = common.make_bot()

        mock_job = mock.MagicMock()
        mock_job.next_run_time = None
        mock_job.id = '1'
        jobs = {
            mock_job.id: mock_job,
        }
        bot.scheduler.get_job.side_effect = lambda job_id: jobs.get(job_id)

        m = common.make_message(text="periodics resume 1",
                                to_me=True, user_id="me")

        h = schedule.ResumeHandler(bot, m)
        h.run(handler.HandlerMatch("1"))

        m.reply_text.assert_called_with(
            'Job `1` has been resumed.',
            prefixed=False, threaded=True)

        mock_job.resume.assert_called()

    def test_not_paused(self):
        bot = common.make_bot()

        mock_job = mock.MagicMock()
        mock_job.next_run_time = self.ZERO_DT
        mock_job.id = '1'
        jobs = {
            mock_job.id: mock_job,
        }
        bot.scheduler.get_job.side_effect = lambda job_id: jobs.get(job_id)

        m = common.make_message(text="periodics resume 1",
                                to_me=True, user_id="me")

        h = schedule.ResumeHandler(bot, m)
        h.run(handler.HandlerMatch("1"))

        m.reply_text.assert_called_with(
            'Job `1` is not paused (so it can not be resumed).',
            prefixed=False, threaded=True)


class PauseHandlerTest(TestCase):
    ZERO_DT = datetime.fromtimestamp(0, pytz.utc)

    def test_expected_handled(self):
        bot = common.make_bot()

        m = common.make_message(text="periodics pause 1", to_me=True)
        self.assertTrue(
            schedule.PauseHandler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="do something else", to_me=True)
        self.assertEqual(
            schedule.PauseHandler.handles(m, c.TARGETED, bot.config), None)

    def test_not_found(self):
        bot = common.make_bot()

        jobs = {}
        bot.scheduler.get_job.side_effect = lambda job_id: jobs.get(job_id)

        m = common.make_message(text="periodics pause 1",
                                to_me=True, user_id="me")

        h = schedule.PauseHandler(bot, m)
        self.assertRaises(excp.NotFound, h.run, handler.HandlerMatch("1"))

    def test_paused(self):
        bot = common.make_bot()

        mock_job = mock.MagicMock()
        mock_job.next_run_time = self.ZERO_DT
        mock_job.id = '1'
        jobs = {
            mock_job.id: mock_job,
        }
        bot.scheduler.get_job.side_effect = lambda job_id: jobs.get(job_id)

        m = common.make_message(text="periodics pause 1",
                                to_me=True, user_id="me")

        h = schedule.PauseHandler(bot, m)
        h.run(handler.HandlerMatch("1"))

        m.reply_text.assert_called_with(
            'Job `1` has been paused.',
            prefixed=False, threaded=True)

        mock_job.pause.assert_called()

    def test_already_paused(self):
        bot = common.make_bot()

        mock_job = mock.MagicMock()
        mock_job.next_run_time = None
        mock_job.id = '1'
        jobs = {
            mock_job.id: mock_job,
        }
        bot.scheduler.get_job.side_effect = lambda job_id: jobs.get(job_id)

        m = common.make_message(text="periodics pause 1",
                                to_me=True, user_id="me")

        h = schedule.PauseHandler(bot, m)
        h.run(handler.HandlerMatch("1"))

        m.reply_text.assert_called_with(
            'Job `1` is already paused.', prefixed=False, threaded=True)


class ScheduleRunOneHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = common.make_bot()

        m = common.make_message(text="periodics run one 1", to_me=True)
        self.assertTrue(
            schedule.RunOneHandler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="do something else", to_me=True)
        self.assertEqual(
            schedule.RunOneHandler.handles(m, c.TARGETED, bot.config), None)

    def test_periodic_no_run_paused(self):
        bot = common.make_bot()

        mock_job = mock.MagicMock()
        mock_job.next_run_time = None
        mock_job.id = '1'
        jobs = {
            mock_job.id: mock_job,
        }
        bot.scheduler.get_job.side_effect = lambda job_id: jobs.get(job_id)
        m = common.make_message(text="periodics run one 1",
                                to_me=True, user_id="me")

        h = schedule.RunOneHandler(bot, m)
        self.assertRaises(RuntimeError, h.run, handler.HandlerMatch("1"))

    def test_periodic_ok(self):
        bot = common.make_bot()

        mock_job = mock.MagicMock()
        mock_job.id = '1'
        jobs = {
            mock_job.id: mock_job,
        }
        bot.scheduler.get_job.side_effect = lambda job_id: jobs.get(job_id)
        m = common.make_message(text="periodics run one 1",
                                to_me=True, user_id="me")

        h = schedule.RunOneHandler(bot, m)
        h.run(handler.HandlerMatch("1"))

        m.reply_text.assert_called_with(
            "Job `1` has had its next run time updated to be"
            " now (hopefully it runs soon).", prefixed=False, threaded=True)

    def test_periodic_no_run_missing(self):
        bot = common.make_bot()

        jobs = {}
        bot.scheduler.get_job.side_effect = lambda job_id: jobs.get(job_id)
        m = common.make_message(text="periodics run one 1",
                                to_me=True, user_id="me")

        h = schedule.RunOneHandler(bot, m)
        self.assertRaises(excp.NotFound, h.run, handler.HandlerMatch("1"))


class ScheduleRunAllHandlerTest(TestCase):
    ZERO_DT = datetime.fromtimestamp(0, pytz.utc)
    IN_ONE_HOUR_DT = datetime.fromtimestamp(time.time() + (60 * 60), pytz.utc)

    def test_expected_handled(self):
        bot = common.make_bot()

        m = common.make_message(text="periodics run all", to_me=True)
        self.assertTrue(
            schedule.RunAllHandler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="do something else", to_me=True)
        self.assertEqual(
            schedule.RunAllHandler.handles(m, c.TARGETED, bot.config), None)

    def test_kick_empty(self):
        bot = common.make_bot()
        jobs = {}
        bot.scheduler.get_jobs.return_value = list(jobs.values())

        m = common.make_message(text="periodics run all",
                                to_me=True, user_id="me")
        h = schedule.RunAllHandler(bot, m)

        h.run(handler.HandlerMatch())
        m.reply_text.assert_called_with(
            "Kicked 0 jobs and skipped 0 jobs.", prefixed=False,
            threaded=True)

    def test_kick_not_empty(self):
        bot = common.make_bot()
        jobs = {}
        for i in range(0, 10):
            job = mock.MagicMock()
            job.next_run_time = self.IN_ONE_HOUR_DT
            job.id = str(i)
            jobs[job.id] = job
        bot.scheduler.get_jobs.return_value = list(jobs.values())

        m = common.make_message(text="periodics run all",
                                to_me=True, user_id="me")
        h = schedule.RunAllHandler(bot, m)

        h.run(handler.HandlerMatch())
        m.reply_text.assert_called_with(
            "Kicked 10 jobs and skipped 0 jobs.",
            prefixed=False, threaded=True)

    def test_kick_not_empty_no_skip_paused(self):
        bot = common.make_bot()
        jobs = {}
        for i in range(0, 10):
            job = mock.MagicMock()
            if i == 0:
                job.next_run_time = self.ZERO_DT
            else:
                if i % 2 == 0:
                    job.next_run_time = self.IN_ONE_HOUR_DT
                else:
                    job.next_run_time = None
            job.id = str(i)
            jobs[job.id] = job
        bot.scheduler.get_jobs.return_value = list(jobs.values())
        bot.scheduler.submitted_jobs = {}
        bot.scheduler.submitted_jobs["1"] = self.ZERO_DT

        m = common.make_message(text="periodics run all",
                                to_me=True, user_id="me")
        h = schedule.RunAllHandler(bot, m)

        h.run(handler.HandlerMatch("skip_paused=false"))
        m.reply_text.assert_called_with(
            "Kicked 10 jobs and skipped 0 jobs.",
            prefixed=False, threaded=True)

    def test_kick_not_empty_skip_paused(self):
        bot = common.make_bot()
        jobs = {}
        for i in range(0, 10):
            job = mock.MagicMock()
            if i % 2 == 0:
                job.next_run_time = self.IN_ONE_HOUR_DT
            else:
                job.next_run_time = None
            job.id = str(i)
            jobs[job.id] = job
        bot.scheduler.get_jobs.return_value = list(jobs.values())

        m = common.make_message(text="periodics run all",
                                to_me=True, user_id="me")
        h = schedule.RunAllHandler(bot, m)

        h.run(handler.HandlerMatch())
        m.reply_text.assert_called_with(
            "Kicked 5 jobs and skipped 5 jobs.",
            prefixed=False, threaded=True)


class ScheduleShowHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = common.make_bot()

        m = common.make_message(text="periodics show", to_me=True)
        self.assertTrue(
            schedule.ShowHandler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="periodics do now show",
                                to_me=True)
        self.assertEqual(
            schedule.ShowHandler.handles(m, c.TARGETED, bot.config), None)

    def test_show_not_empty(self):
        bot = common.make_bot()
        job = mock.MagicMock()
        job.id = str(1)
        jobs = [job]
        bot.scheduler.timezone = pytz.utc
        bot.scheduler.get_jobs.return_value = list(jobs)

        m = common.make_message(text="periodics show",
                                to_me=True, user_id="me")
        h = schedule.ShowHandler(bot, m)

        h.run(handler.HandlerMatch())

        m.reply_attachments.assert_called_with(
            text="Scheduler is in `UNKNOWN` state with the following jobs:",
            attachments=mock.ANY, link_names=True,
            as_user=True, channel=None,
            log=mock.ANY, thread_ts=mock.ANY)

    def test_show_empty(self):
        bot = common.make_bot()
        jobs = {}
        bot.scheduler.timezone = pytz.utc
        bot.scheduler.get_jobs.return_value = list(jobs.values())

        m = common.make_message(text="periodics show",
                                to_me=True, user_id="me")
        h = schedule.ShowHandler(bot, m)

        h.run(handler.HandlerMatch())

        m.reply_text.assert_called_with(
            "Scheduler is in `UNKNOWN` state.", prefixed=False, threaded=True)
