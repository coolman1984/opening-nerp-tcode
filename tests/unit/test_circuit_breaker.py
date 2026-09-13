"""A screen that has failed for days should stop burning the recovery budget.

Inspired by the dead-letter-queue / circuit-breaker pattern: isolate what
will not succeed no matter how many times it is retried, without ever
blocking it forever - any real success closes it, and --force always
attempts anyway.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.application import circuit, run_many_uc
from gmes.contracts import RunResult, RunSpec


class TemporaryRuntime(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.enterContext(patch.dict(os.environ, {"LOCALAPPDATA": directory.name}))


class BreakerStateTests(TemporaryRuntime):
    def test_a_screen_that_has_never_failed_starts_closed(self):
        self.assertIsNone(circuit.check("P1112UM00"))
        self.assertFalse(circuit.load("P1112UM00").is_open())

    def test_the_breaker_opens_only_at_the_threshold_not_before(self):
        for _ in range(circuit.DEFAULT_THRESHOLD - 1):
            circuit.record_failure("P1112UM00", "no complete .xlsx appeared")
        self.assertIsNone(circuit.check("P1112UM00"))
        circuit.record_failure("P1112UM00", "no complete .xlsx appeared")
        self.assertIsNotNone(circuit.check("P1112UM00"))

    def test_the_skip_message_names_the_screen_the_reason_and_the_way_out(self):
        for _ in range(circuit.DEFAULT_THRESHOLD):
            circuit.record_failure("P1112UM00", "no filter matches 'porder'")
        message = circuit.check("P1112UM00")
        self.assertIn("P1112UM00", message)
        self.assertIn("no filter matches 'porder'", message)
        self.assertIn("--force", message)

    def test_any_success_closes_the_breaker_outright(self):
        for _ in range(circuit.DEFAULT_THRESHOLD + 2):
            circuit.record_failure("P1112UM00", "timeout")
        circuit.record_success("P1112UM00")
        self.assertIsNone(circuit.check("P1112UM00"))
        self.assertEqual(circuit.load("P1112UM00").consecutive_failures, 0)

    def test_screens_are_tracked_independently(self):
        for _ in range(circuit.DEFAULT_THRESHOLD):
            circuit.record_failure("P1112UM00", "broken")
        self.assertIsNone(circuit.check("P1113WM00"))

    def test_a_corrupt_history_file_is_treated_as_never_failed(self):
        path = circuit._path_for("P1112UM00")
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(circuit.load("P1112UM00").consecutive_failures, 0)

    def test_a_reason_is_never_stored_unbounded(self):
        circuit.record_failure("P1112UM00", "x" * 10000)
        self.assertLessEqual(len(circuit.load("P1112UM00").last_reason), 300)

    def test_a_blank_code_is_rejected_rather_than_silently_reused(self):
        with self.assertRaises(ValueError):
            circuit._path_for("   ")

    def test_path_like_characters_can_never_escape_the_circuit_directory(self):
        """Only letters and digits survive into the filename, so a code
        carrying '../' or a separator cannot be used to read or write
        anywhere outside circuit_dir()."""
        path = circuit._path_for("../../etc/passwd")
        self.assertEqual(path.parent, circuit.circuit_dir())
        self.assertNotIn("..", path.name)
        self.assertNotIn(os.sep, path.name)


class BatchCircuitIntegrationTests(TemporaryRuntime):
    """The breaker skips a broken screen but never blocks the rest of the batch."""

    def setUp(self):
        super().setUp()
        self.session = Mock(ws=object())

    def test_a_broken_screen_is_skipped_and_the_batch_continues(self):
        for _ in range(circuit.DEFAULT_THRESHOLD):
            circuit.record_failure("BROKEN01", "no complete .xlsx appeared")

        def run(ws, spec, log):
            self.assertNotEqual(spec.screen_code, "BROKEN01")
            return RunResult(spec.screen_code, True, rows=5)

        with patch.object(run_many_uc, "run_screen", side_effect=run):
            results = run_many_uc.run_many(
                self.session, [RunSpec("BROKEN01"), RunSpec("GOOD01")], log=lambda _: None)
        self.assertEqual([r.ok for r in results], [False, True])
        self.assertIn("--force", results[0].error)

    def test_a_screen_that_never_opened_leaves_the_session_untouched(self):
        for _ in range(circuit.DEFAULT_THRESHOLD):
            circuit.record_failure("BROKEN01", "timeout")
        with patch.object(run_many_uc, "run_screen") as run_screen:
            run_many_uc.run_many(self.session, [RunSpec("BROKEN01")], log=lambda _: None)
        run_screen.assert_not_called()
        self.session.settle.assert_not_called()

    def test_force_bypasses_the_breaker_and_attempts_the_screen_anyway(self):
        for _ in range(circuit.DEFAULT_THRESHOLD):
            circuit.record_failure("BROKEN01", "timeout")
        with patch.object(run_many_uc, "run_screen",
                          return_value=RunResult("BROKEN01", True, rows=1)):
            results = run_many_uc.run_many(
                self.session, [RunSpec("BROKEN01", force=True)], log=lambda _: None)
        self.assertTrue(results[0].ok)

    def test_a_success_after_being_forced_resets_the_history(self):
        for _ in range(circuit.DEFAULT_THRESHOLD):
            circuit.record_failure("BROKEN01", "timeout")
        with patch.object(run_many_uc, "run_screen",
                          return_value=RunResult("BROKEN01", True, rows=1)):
            run_many_uc.run_many(self.session, [RunSpec("BROKEN01", force=True)],
                                 log=lambda _: None)
        self.assertIsNone(circuit.check("BROKEN01"))

    def test_a_genuine_run_failure_still_records_and_stops_the_batch(self):
        """Only a screen the breaker skipped continues the batch; a screen
        that was actually opened and failed keeps the existing fail-fast
        rule, because its state on screen is no longer provably clear."""
        with patch.object(run_many_uc, "run_screen",
                          side_effect=RuntimeError("unrecognised window")), \
             patch.object(run_many_uc, "screenshot_on_failure"):
            results = run_many_uc.run_many(
                self.session, [RunSpec("FLAKY01"), RunSpec("NEXT01")], log=lambda _: None)
        self.assertEqual([r.ok for r in results], [False, False])
        self.assertIn("not run", results[1].error)
        self.assertEqual(circuit.load("FLAKY01").consecutive_failures, 1)

    def test_repeated_genuine_failures_across_separate_batches_eventually_trip(self):
        for _ in range(circuit.DEFAULT_THRESHOLD):
            with patch.object(run_many_uc, "run_screen",
                              side_effect=RuntimeError("still broken")), \
                 patch.object(run_many_uc, "screenshot_on_failure"):
                run_many_uc.run_many(self.session, [RunSpec("FLAKY01")], log=lambda _: None)
        with patch.object(run_many_uc, "run_screen") as run_screen:
            results = run_many_uc.run_many(self.session, [RunSpec("FLAKY01")],
                                           log=lambda _: None)
        run_screen.assert_not_called()
        self.assertIn("--force", results[0].error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
