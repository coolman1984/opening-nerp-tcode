"""The recovery ladder: what is worth retrying, after what repair, how often."""
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.application import recovery, run_many_uc, session_uc
from gmes.contracts import LoginAttempt, LoginOutcome, RunResult, RunSpec


class ClassificationTests(unittest.TestCase):
    """A refusal is a finished answer; repeating it only delays the report."""

    def test_this_projects_own_refusals_are_never_retried(self):
        for message in ("no filter matches 'porder' on this screen",
                        "'date' is ambiguous - matches: a, b",
                        "which grid? this screen has: a, b",
                        "paramPlant did not take: asked for VD",
                        "Refusing to query the wrong organisation",
                        "the remembered screen shape changed",
                        "the query returned no rows - nothing exported",
                        "a date-constrained run requires --verify COLUMN"):
            with self.subTest(message=message):
                self.assertTrue(recovery.is_a_decision(RuntimeError(message)))

    def test_a_bad_argument_is_a_decision_whatever_it_says(self):
        self.assertTrue(recovery.is_a_decision(ValueError("--set needs NAME=VALUE")))

    def test_things_that_actually_broke_are_retried(self):
        for error in (RuntimeError("P1112UM00 opened but never finished building"),
                      RuntimeError("the Excel export did not deliver a file in 3 attempts"),
                      RuntimeError("Could not attach to the G-MES tab after 4 attempts"),
                      ConnectionResetError("connection lost")):
            with self.subTest(error=error):
                self.assertFalse(recovery.is_a_decision(error))


class LadderTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(recovery.heartbeat, "beat"))
        self.session = Mock(ws="socket-1")
        self.repairs = []
        for rung in ("settle", "reset_page", "cold_start"):
            getattr(self.session, rung).side_effect = \
                lambda rung=rung: self.repairs.append(rung)

    def ladder(self, **policy):
        return recovery.Ladder(self.session, recovery.RecoveryPolicy(**policy),
                               log=lambda _message: None)

    def failing(self, times, error=None):
        """Work that fails `times` times and then succeeds."""
        calls = []

        def work(ws):
            calls.append(ws)
            if len(calls) <= times:
                raise error or RuntimeError("the page never finished building")
            return "delivered"

        return work, calls

    def test_work_that_succeeds_first_time_repairs_nothing(self):
        work, calls = self.failing(0)
        self.assertEqual(self.ladder().run(work), "delivered")
        self.assertEqual(self.repairs, [])
        self.assertEqual(len(calls), 1)

    def test_the_rungs_are_climbed_in_order_and_each_one_is_different(self):
        work, calls = self.failing(3)
        self.assertEqual(self.ladder().run(work), "delivered")
        self.assertEqual(self.repairs, ["settle", "reset_page", "cold_start"])
        self.assertEqual(len(calls), 4)

    def test_a_cheaper_rung_that_works_never_reaches_the_browser_restart(self):
        work, _calls = self.failing(1)
        self.assertEqual(self.ladder().run(work), "delivered")
        self.assertEqual(self.repairs, ["settle"])
        self.session.cold_start.assert_not_called()

    def test_a_refusal_stops_at_once_without_any_repair(self):
        work, calls = self.failing(1, RuntimeError("no filter matches 'porder'"))
        with self.assertRaisesRegex(RuntimeError, "no filter matches"):
            self.ladder().run(work)
        self.assertEqual(self.repairs, [])
        self.assertEqual(len(calls), 1)

    def test_the_ladder_has_a_top_and_reports_the_last_real_reason(self):
        work, calls = self.failing(99)
        with self.assertRaisesRegex(RuntimeError, "never finished building"):
            self.ladder().run(work)
        self.assertEqual(self.repairs, ["settle", "reset_page", "cold_start"])
        self.assertEqual(len(calls), 4)

    def test_the_browser_restart_is_allowed_only_as_often_as_the_policy_says(self):
        work, _calls = self.failing(99)
        with self.assertRaises(RuntimeError):
            self.ladder(in_place_attempts=1, cold_starts=2).run(work)
        self.assertEqual(self.repairs, ["cold_start", "cold_start"])

    def test_an_exhausted_time_budget_stops_even_with_rungs_left(self):
        work, calls = self.failing(99)
        with self.assertRaises(RuntimeError):
            self.ladder(time_budget_s=0).run(work)
        self.assertEqual(self.repairs, [])
        self.assertEqual(len(calls), 1)

    def test_each_attempt_uses_the_socket_the_session_holds_now(self):
        """A restart replaces the connection; the work must get the new one."""
        def restart():
            self.repairs.append("cold_start")
            self.session.ws = "socket-2"

        self.session.cold_start.side_effect = restart
        work, calls = self.failing(3)
        self.ladder().run(work)
        self.assertEqual(calls, ["socket-1", "socket-1", "socket-1", "socket-2"])


class BatchRecoveryTests(unittest.TestCase):
    """The batch gets the ladder, and a repaired screen still counts as run."""

    def setUp(self):
        # The circuit breaker, checkpoint, and heartbeat (Phase 50/51/52)
        # are exercised by their own dedicated tests with an isolated
        # LOCALAPPDATA; here they are stubbed so this suite never touches
        # real disk state.
        self.enterContext(patch.object(run_many_uc.circuit, "check", return_value=None))
        self.enterContext(patch.object(run_many_uc.circuit, "record_success"))
        self.enterContext(patch.object(run_many_uc.circuit, "record_failure"))
        self.enterContext(patch.object(run_many_uc.checkpoint, "completed", return_value={}))
        self.enterContext(patch.object(run_many_uc.checkpoint, "record"))
        self.enterContext(patch.object(run_many_uc.checkpoint, "clear"))
        self.enterContext(patch.object(run_many_uc.heartbeat, "beat"))
        self.enterContext(patch.object(recovery.heartbeat, "beat"))

    def test_a_screen_that_recovers_is_reported_as_the_success_it_became(self):
        session, attempts = Mock(ws=object()), []

        def run(ws, spec, log):
            attempts.append(spec.screen_code)
            if len(attempts) == 1:
                raise RuntimeError("the page never finished building")
            return RunResult(spec.screen_code, True, rows=7)

        with patch.object(run_many_uc, "run_screen", side_effect=run):
            results = run_many_uc.run_many(session, [RunSpec("A")], log=lambda _: None)
        self.assertEqual([result.ok for result in results], [True])
        self.assertEqual(results[0].rows, 7)
        session.settle.assert_called_once()

    def test_a_refusal_is_not_retried_and_still_stops_the_batch(self):
        session = Mock(ws=object())
        with patch.object(run_many_uc, "run_screen",
                          side_effect=RuntimeError("the query returned no rows")), \
             patch.object(run_many_uc, "screenshot_on_failure"):
            results = run_many_uc.run_many(session, [RunSpec("A"), RunSpec("B")],
                                           log=lambda _: None)
        self.assertEqual([result.ok for result in results], [False, False])
        session.settle.assert_not_called()
        session.cold_start.assert_not_called()


class LiveSessionTests(unittest.TestCase):
    """The repairs themselves - each one observes rather than assumes."""

    def setUp(self):
        self.ws = Mock()
        self.session = session_uc.LiveSession(self.ws, {"show_browser": False},
                                              log=lambda _message: None)

    def test_a_healthy_socket_is_kept_and_a_dead_one_is_replaced(self):
        with patch.object(session_uc, "evaluate", return_value={"alive": True}), \
             patch.object(session_uc, "connect_gmes") as attach:
            self.assertFalse(self.session._reattach_if_dead())
        attach.assert_not_called()

        with patch.object(session_uc, "evaluate", side_effect=OSError("socket gone")), \
             patch.object(session_uc, "connect_gmes", return_value="fresh") as attach:
            self.assertTrue(self.session._reattach_if_dead())
        self.assertEqual(self.session.ws, "fresh")

    def test_settle_clears_notices_on_a_connection_it_has_proved_is_live(self):
        with patch.object(session_uc, "evaluate", return_value={"alive": True}), \
             patch.object(session_uc.popups, "close_notices",
                          return_value=(["공지사항"], [])) as notices:
            self.session.settle()
        notices.assert_called_once_with(self.ws)

    def test_reset_page_clears_both_caches_before_reloading(self):
        order = []
        with patch.object(session_uc, "evaluate", return_value={"alive": True}), \
             patch.object(session_uc, "storage_state", return_value={"bytes": 4 << 20}), \
             patch.object(session_uc, "prune_nexacro_cache",
                          side_effect=lambda ws: order.append("engine cache") or {"removed": 9}), \
             patch.object(session_uc, "clear_browser_cache",
                          side_effect=lambda ws: order.append("browser cache") or True), \
             patch.object(session_uc, "send", side_effect=lambda *a, **k: order.append("reload")), \
             patch.object(self.session, "_wait_for_a_usable_page"):
            self.session.reset_page()
        self.assertEqual(order, ["engine cache", "browser cache", "reload"])

    def test_a_cold_start_never_refreshes_the_profile_it_restarts_onto(self):
        with patch.object(session_uc, "close_browser") as close, \
             patch.object(session_uc, "sign_in",
                          return_value=LoginAttempt(LoginOutcome.OK)) as login, \
             patch.object(session_uc, "connect_gmes", return_value="fresh"):
            self.session.cold_start()
        close.assert_called_once()
        self.assertEqual(self.session.ws, "fresh")
        self.assertNotIn("refresh_profile", login.call_args.kwargs)

    def test_a_cold_start_that_cannot_sign_in_says_so_instead_of_carrying_on(self):
        with patch.object(session_uc, "close_browser"), \
             patch.object(session_uc, "sign_in", return_value=LoginAttempt(
                 LoginOutcome.REJECTED, "no saved credentials")), \
             patch.object(session_uc, "connect_gmes") as attach:
            with self.assertRaisesRegex(RuntimeError, "no saved credentials"):
                self.session.cold_start()
        attach.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
