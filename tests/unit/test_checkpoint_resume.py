"""Resuming a batch a full process crash interrupted, without redoing
screens that already delivered a real file.

Unlike a caught exception (the recovery ladder) or a screen broken for
days (the circuit breaker), this covers the process itself dying - power
loss, a forced reboot, the wrong task killed in Task Scheduler. The next
launch of the SAME command should not repeat work a crash could not undo.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.application import checkpoint, run_many_uc
from gmes.contracts import RunResult, RunSpec


class TemporaryRuntime(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.enterContext(patch.dict(os.environ, {"LOCALAPPDATA": directory.name}))


def isolate_circuit(test):
    """The circuit breaker (Phase 50) is exercised by its own tests; here it
    is stubbed so a checkpoint test never has to also satisfy its policy."""
    test.enterContext(patch.object(run_many_uc.circuit, "check", return_value=None))
    test.enterContext(patch.object(run_many_uc.circuit, "record_success"))
    test.enterContext(patch.object(run_many_uc.circuit, "record_failure"))


class SignatureTests(TemporaryRuntime):
    def test_the_same_request_produces_the_same_signature(self):
        specs = [RunSpec("P1112UM00", division="VD", date_from="20260909", date_to="20260909")]
        self.assertEqual(checkpoint._signature(specs), checkpoint._signature(list(specs)))

    def test_a_different_date_is_a_different_batch(self):
        """The ordinary nightly case: 'yesterday' computed fresh each night
        naturally starts a new batch with nothing to resume."""
        today = [RunSpec("P1112UM00", date_from="20260912", date_to="20260912")]
        yesterday = [RunSpec("P1112UM00", date_from="20260911", date_to="20260911")]
        self.assertNotEqual(checkpoint._signature(today), checkpoint._signature(yesterday))

    def test_a_different_filter_value_is_a_different_batch(self):
        a = [RunSpec("P1112UM00", sets={"plant": "VD"})]
        b = [RunSpec("P1112UM00", sets={"plant": "MOBILE"})]
        self.assertNotEqual(checkpoint._signature(a), checkpoint._signature(b))


class RecordAndResumeTests(TemporaryRuntime):
    def specs(self):
        return [RunSpec("A"), RunSpec("B")]

    def test_nothing_recorded_means_nothing_to_resume(self):
        self.assertEqual(checkpoint.completed(self.specs()), {})

    def test_only_a_real_success_is_ever_recorded(self):
        checkpoint.record(self.specs(), RunResult("A", ok=False, error="no rows"))
        self.assertEqual(checkpoint.completed(self.specs()), {})

    def test_a_recorded_success_is_returned_for_the_same_batch_only(self):
        specs = self.specs()
        checkpoint.record(specs, RunResult("A", ok=True, rows=42, files=("out.xlsx",)))
        self.assertIn("A", checkpoint.completed(specs))
        self.assertEqual(checkpoint.completed(specs)["A"]["rows"], 42)
        # A batch that asks for something different has nothing to resume,
        # even though the screen code is the same.
        different = [RunSpec("A", division="VD"), RunSpec("B")]
        self.assertEqual(checkpoint.completed(different), {})

    def test_resumed_result_reports_the_recorded_facts_only(self):
        result = checkpoint.resumed_result("A", {"rows": 9, "files": ["x.csv"], "duration_s": 1.5})
        self.assertTrue(result.ok)
        self.assertEqual(result.rows, 9)
        self.assertEqual(result.files, ("x.csv",))

    def test_clearing_removes_the_record_for_that_exact_batch(self):
        specs = self.specs()
        checkpoint.record(specs, RunResult("A", ok=True, rows=1))
        checkpoint.clear(specs)
        self.assertEqual(checkpoint.completed(specs), {})

    def test_clearing_a_batch_with_no_record_is_a_safe_no_op(self):
        checkpoint.clear(self.specs())   # must not raise

    def test_a_stale_record_is_treated_as_though_it_never_existed(self):
        """A fixed command run again by mistake a week later must not
        silently skip work on the strength of an old crash."""
        specs = self.specs()
        checkpoint.record(specs, RunResult("A", ok=True, rows=1))
        path = checkpoint._path_for(specs)
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        data["started"] = "2020-01-01 00:00:00"
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(checkpoint.completed(specs), {})

    def test_a_corrupt_record_is_treated_as_though_it_never_existed(self):
        specs = self.specs()
        checkpoint._path_for(specs).write_text("{not json", encoding="utf-8")
        self.assertEqual(checkpoint.completed(specs), {})


class RunManyResumeTests(TemporaryRuntime):
    """The behaviour operators and the nightly job actually see."""

    def setUp(self):
        super().setUp()
        isolate_circuit(self)
        self.session = Mock(ws=object())

    def test_a_screen_already_delivered_is_skipped_and_the_browser_untouched(self):
        specs = [RunSpec("A"), RunSpec("B")]
        checkpoint.record(specs, RunResult("A", ok=True, rows=99, files=("a.xlsx",)))

        attempted = []
        def run(ws, spec, log):
            attempted.append(spec.screen_code)
            return RunResult(spec.screen_code, ok=True, rows=1)

        with patch.object(run_many_uc, "run_screen", side_effect=run):
            results = run_many_uc.run_many(self.session, specs, log=lambda _: None)
        self.assertEqual(attempted, ["B"])          # A was never opened
        self.assertEqual(results[0].rows, 99)       # A's resumed result, not re-run
        self.assertTrue(all(result.ok for result in results))

    def test_a_full_process_crash_is_simulated_by_an_uncaught_base_exception(self):
        """A real crash (power loss, a killed task) never reaches run_many's
        `except Exception` - nothing runs after it, including recording the
        screen it died on. BaseException (not Exception) reproduces that:
        it propagates straight out, exactly like the process disappearing."""
        specs = [RunSpec("A"), RunSpec("B"), RunSpec("C")]

        def crashes_on_b(ws, spec, log):
            if spec.screen_code == "A":
                return RunResult("A", ok=True, rows=10)
            raise BaseException("the process is gone; nothing after this line runs")

        with patch.object(run_many_uc, "run_screen", side_effect=crashes_on_b):
            with self.assertRaises(BaseException):
                run_many_uc.run_many(self.session, specs, log=lambda _: None)
        # A was recorded before the crash; B and C never got that far.
        self.assertIn("A", checkpoint.completed(specs))

        # The next launch is a brand new process with no memory of any of
        # this - only the file on disk says A is already done.
        attempted = []
        def run(ws, spec, log):
            attempted.append(spec.screen_code)
            return RunResult(spec.screen_code, ok=True, rows=1)

        with patch.object(run_many_uc, "run_screen", side_effect=run):
            results = run_many_uc.run_many(self.session, specs, log=lambda _: None)
        self.assertEqual(attempted, ["B", "C"])     # A was not redone
        self.assertEqual(len(results), 3)
        self.assertTrue(all(result.ok for result in results))

    def test_resume_false_ignores_any_saved_progress(self):
        specs = [RunSpec("A")]
        checkpoint.record(specs, RunResult("A", ok=True, rows=99))
        attempted = []
        with patch.object(run_many_uc, "run_screen",
                          side_effect=lambda ws, spec, log: attempted.append(spec.screen_code)
                          or RunResult(spec.screen_code, ok=True, rows=1)):
            run_many_uc.run_many(self.session, specs, log=lambda _: None, resume=False)
        self.assertEqual(attempted, ["A"])

    def test_only_a_success_after_the_recorded_one_is_ever_skipped(self):
        """A screen that failed is retried fresh, never silently reused."""
        specs = [RunSpec("A")]
        checkpoint.record(specs, RunResult("A", ok=False, error="never recorded"))
        attempted = []
        with patch.object(run_many_uc, "run_screen",
                          side_effect=lambda ws, spec, log: attempted.append(spec.screen_code)
                          or RunResult(spec.screen_code, ok=True, rows=1)):
            run_many_uc.run_many(self.session, specs, log=lambda _: None)
        self.assertEqual(attempted, ["A"])

    def test_a_fully_successful_batch_clears_its_own_record(self):
        specs = [RunSpec("A")]
        with patch.object(run_many_uc, "run_screen",
                          return_value=RunResult("A", ok=True, rows=1)):
            run_many_uc.run_many(self.session, specs, log=lambda _: None)
        self.assertEqual(checkpoint.completed(specs), {})

    def test_a_batch_that_still_has_a_failure_keeps_its_record_for_next_time(self):
        specs = [RunSpec("A"), RunSpec("B")]
        with patch.object(run_many_uc, "run_screen", side_effect=[
                RunResult("A", ok=True, rows=1), RuntimeError("still broken")]), \
             patch.object(run_many_uc, "screenshot_on_failure"):
            run_many_uc.run_many(self.session, specs, log=lambda _: None)
        self.assertIn("A", checkpoint.completed(specs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
