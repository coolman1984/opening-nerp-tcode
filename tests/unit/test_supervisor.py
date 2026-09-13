"""The outer watchdog: acts only on silence, never on an ordinary failure.

heartbeat.py is exercised directly with an isolated LOCALAPPDATA; the
supervisor is exercised against a fake child process so no real `gmes`
process, and no real wall-clock wait, is ever needed.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.application import heartbeat, supervisor_uc


class TemporaryRuntime(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.enterContext(patch.dict(os.environ, {"LOCALAPPDATA": directory.name}))


class HeartbeatTests(TemporaryRuntime):
    def test_nothing_recorded_has_no_age(self):
        self.assertIsNone(heartbeat.read())
        self.assertIsNone(heartbeat.age_seconds())

    def test_a_beat_is_readable_immediately_and_barely_aged(self):
        heartbeat.beat("doing something")
        data = heartbeat.read()
        self.assertEqual(data["detail"], "doing something")
        self.assertIn("pid", data)
        self.assertLess(heartbeat.age_seconds(), 5)

    def test_clear_removes_the_record(self):
        heartbeat.beat("x")
        heartbeat.clear()
        self.assertIsNone(heartbeat.read())

    def test_clearing_when_nothing_exists_is_a_safe_no_op(self):
        heartbeat.clear()   # must not raise

    def test_a_corrupt_file_reads_as_no_beat_rather_than_crashing(self):
        heartbeat.heartbeat_path().write_text("{not json", encoding="utf-8")
        self.assertIsNone(heartbeat.read())
        self.assertIsNone(heartbeat.age_seconds())

    def test_a_long_detail_is_never_stored_unbounded(self):
        heartbeat.beat("x" * 10000)
        self.assertLessEqual(len(heartbeat.read()["detail"]), 200)


class FakeProcess:
    """Stands in for subprocess.Popen: a scripted exit-code sequence via
    .poll(), and recorded terminate/kill/wait calls."""

    def __init__(self, poll_sequence):
        self._poll = iter(poll_sequence)
        self.pid = 4242
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self):
        return next(self._poll, self._poll_last)

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.waited = True


class SupervisorCommandTests(unittest.TestCase):
    def test_a_source_checkout_is_invoked_through_dash_m_gmes(self):
        with patch.object(supervisor_uc.sys, "frozen", False, create=True):
            command = supervisor_uc._command(["run", "P1112UM00"])
        self.assertEqual(command, [sys.executable, "-m", "gmes", "run", "P1112UM00"])

    def test_a_frozen_build_is_invoked_directly(self):
        with patch.object(supervisor_uc.sys, "frozen", True, create=True):
            command = supervisor_uc._command(["run", "P1112UM00"])
        self.assertEqual(command, [sys.executable, "run", "P1112UM00"])


class SupervisorRunTests(TemporaryRuntime):
    """`age_seconds` and `time.sleep` are controlled directly, so the whole
    suite runs without a real wall-clock wait."""

    def setUp(self):
        super().setUp()
        self.enterContext(patch.object(supervisor_uc.time, "sleep"))
        self.enterContext(patch.object(supervisor_uc.subprocess, "run"))

    def spawn(self, process):
        return Mock(return_value=process)

    def test_a_process_that_exits_cleanly_is_reported_exactly_as_it_exited(self):
        process = FakeProcess([0])
        process._poll_last = 0
        result = supervisor_uc.run_supervised(
            ["run", "P1112UM00"], spawn=self.spawn(process), log=lambda _: None)
        self.assertEqual(result, 0)
        self.assertFalse(process.terminated)

    def test_a_process_that_fails_is_reported_exactly_as_it_failed_never_killed(self):
        """Failing is not the same as hanging - the supervisor must never
        turn an ordinary bad exit code into a kill-and-restart."""
        process = FakeProcess([1])
        process._poll_last = 1
        result = supervisor_uc.run_supervised(
            ["run", "P1112UM00"], spawn=self.spawn(process), log=lambda _: None)
        self.assertEqual(result, 1)
        self.assertFalse(process.terminated)

    def test_a_process_that_never_beats_is_killed_after_the_stale_window(self):
        process = FakeProcess([None] * 50)
        process._poll_last = None
        with patch.object(supervisor_uc.heartbeat, "age_seconds", return_value=9999):
            result = supervisor_uc.run_supervised(
                ["run", "P1112UM00"], spawn=self.spawn(process), stale_after=10,
                restarts=0, log=lambda _: None)
        self.assertEqual(result, 1)

    def test_a_process_that_keeps_beating_is_never_killed_however_long_it_runs(self):
        process = FakeProcess([None, None, None, 0])
        process._poll_last = 0
        with patch.object(supervisor_uc.heartbeat, "age_seconds", return_value=1):
            result = supervisor_uc.run_supervised(
                ["run", "P1112UM00"], spawn=self.spawn(process), stale_after=10,
                log=lambda _: None)
        self.assertEqual(result, 0)

    def test_a_stuck_process_gets_one_restart_by_default_then_gives_up(self):
        first = FakeProcess([None] * 5)
        first._poll_last = None
        second = FakeProcess([None] * 5)
        second._poll_last = None
        spawn = Mock(side_effect=[first, second])
        with patch.object(supervisor_uc.heartbeat, "age_seconds", return_value=9999):
            result = supervisor_uc.run_supervised(
                ["run", "P1112UM00"], spawn=spawn, stale_after=10, log=lambda _: None)
        self.assertEqual(result, 1)
        self.assertEqual(spawn.call_count, 2)

    def test_a_restart_that_then_succeeds_is_reported_as_the_success_it_became(self):
        first = FakeProcess([None] * 5)
        first._poll_last = None
        second = FakeProcess([0])
        second._poll_last = 0
        spawn = Mock(side_effect=[first, second])
        ages = iter([9999, 9999, 0])
        with patch.object(supervisor_uc.heartbeat, "age_seconds",
                          side_effect=lambda: next(ages, 0)):
            result = supervisor_uc.run_supervised(
                ["run", "P1112UM00"], spawn=spawn, stale_after=10, log=lambda _: None)
        self.assertEqual(result, 0)

    def test_a_stuck_process_on_windows_is_killed_by_pid_never_by_image_name(self):
        """CLAUDE.md 2.6: never taskkill every chrome.exe. Only this
        process's own tree, by PID."""
        process = FakeProcess([None] * 5)
        process._poll_last = None
        with patch.object(supervisor_uc.sys, "platform", "win32"), \
             patch.object(supervisor_uc.heartbeat, "age_seconds", return_value=9999):
            supervisor_uc.run_supervised(["run", "P1112UM00"], spawn=self.spawn(process),
                                         stale_after=10, restarts=0, log=lambda _: None)
        args = supervisor_uc.subprocess.run.call_args.args[0]
        self.assertIn(str(process.pid), args)
        self.assertNotIn("chrome.exe", args)

    def test_a_fresh_run_never_inherits_a_stale_beat_from_a_previous_attempt(self):
        heartbeat.beat("leftover from a run that is not this one")
        process = FakeProcess([0])
        process._poll_last = 0
        supervisor_uc.run_supervised(["run", "P1112UM00"], spawn=self.spawn(process),
                                     log=lambda _: None)
        # heartbeat.clear() at the top must have removed it before anything
        # was spawned - the child never got a chance to write its own.
        self.assertIsNone(heartbeat.read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
