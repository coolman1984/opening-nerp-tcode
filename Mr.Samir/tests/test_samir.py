"""Offline tests for Samir Export (Mr.Samir/). No browser, no network.

    python Mr.Samir/tests/test_samir.py

They guard the DECISION logic - which rows are picked, when a cell may be clicked,
which dialog boxes get ticked, that a file is never overwritten, that Stop works,
that the engine copies are identical to the root modules. They cannot prove the
browser half; that was proven live (HISTORY.md, Phase 111).
"""
import csv
import os
import sys
import tempfile
import threading
import time
import unittest
from tkinter import ttk
from unittest import mock

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
sys.path.insert(0, APP)

import sync_engine                    # noqa: E402
import samir_runner as sr             # noqa: E402


def rows_of(statuses):
    return [{"outInspLotStatusNm": s, "planYmd": "20260901", "modelCode": f"M{i}",
             "outInspLotNo": f"LOT{i}"} for i, s in enumerate(statuses)]


class EngineCopiesStayIdentical(unittest.TestCase):
    def test_every_copy_matches_its_root_original(self):
        self.assertEqual(sync_engine.check(), [])

    def test_a_changed_copy_is_reported(self):
        target = os.path.join(sync_engine.ENGINE, "gmes_redact.py")
        with open(target, "rb") as fh:
            original = fh.read()
        try:
            with open(target, "ab") as fh:
                fh.write(b"\n# tampered\n")
            problems = sync_engine.check()
        finally:
            with open(target, "wb") as fh:
                fh.write(original)
        self.assertTrue(any("gmes_redact" in p for p in problems))


class SettingsAreCheckedBeforeAnythingOpens(unittest.TestCase):
    def test_defaults_are_valid(self):
        self.assertEqual(sr.validate_settings(sr.Settings()), [])

    def test_period_shapes(self):
        self.assertTrue(sr.validate_settings(sr.Settings(period="2026-09")))
        self.assertTrue(sr.validate_settings(sr.Settings(period="202613")))
        self.assertTrue(sr.validate_settings(sr.Settings(period_mode="Daily", period="202609")))
        self.assertTrue(sr.validate_settings(sr.Settings(period_mode="Daily", period="20260231")))
        self.assertEqual(sr.validate_settings(sr.Settings(period_mode="Daily", period="20260930")), [])
        self.assertEqual(sr.validate_settings(sr.Settings(period="202610")), [])

    def test_numbers_and_choices(self):
        self.assertTrue(sr.validate_settings(sr.Settings(start_row=0)))
        self.assertTrue(sr.validate_settings(sr.Settings(count=-1)))
        self.assertTrue(sr.validate_settings(sr.Settings(on_error="ignore")))
        self.assertTrue(sr.validate_settings(sr.Settings(dialog_grids=[])))
        self.assertTrue(sr.validate_settings(sr.Settings(division="  ")))

    def test_several_grids_need_a_single_file(self):
        two = ["a", "b"]
        self.assertTrue(sr.validate_settings(sr.Settings(dialog_grids=two, single_file=False)))
        self.assertTrue(sr.validate_settings(sr.Settings(dialog_grids=two, single_file=None)))
        self.assertEqual(sr.validate_settings(sr.Settings(dialog_grids=two, single_file=True)), [])

    def test_filters_and_name_pattern(self):
        self.assertTrue(sr.validate_settings(sr.Settings(extra_filters=["Model"])))
        self.assertTrue(sr.validate_settings(sr.Settings(extra_filters=["=x"])))
        self.assertEqual(sr.validate_settings(sr.Settings(extra_filters=["Model=UA65"])), [])
        self.assertTrue(sr.validate_settings(sr.Settings(name_pattern="{plan}_{other}")))

    def test_default_period_follows_the_calendar(self):
        from datetime import datetime
        self.assertEqual(sr.default_period("Monthly", datetime(2026, 10, 3)), "202610")
        self.assertEqual(sr.default_period("Daily", datetime(2026, 10, 3)), "20261003")

    def test_unknown_saved_keys_are_ignored(self):
        s = sr.Settings.from_dict({"division": "VD", "no_such_setting": 1})
        self.assertEqual(s.division, "VD")


class WhichRowsAreExported(unittest.TestCase):
    def test_only_the_link_value_is_picked(self):
        rows = rows_of(["PASS", "In progress", "PASS", "Outgoing Revoke", "PASS"])
        picked, other = sr.select_rows(rows, "outInspLotStatusNm", "PASS", 1, 0)
        self.assertEqual((picked, other), ([0, 2, 4], 2))

    def test_start_row_is_a_grid_row_number(self):
        rows = rows_of(["PASS"] * 6)
        self.assertEqual(sr.select_rows(rows, "outInspLotStatusNm", "PASS", 4, 0)[0], [3, 4, 5])

    def test_count_limits_and_zero_means_all(self):
        rows = rows_of(["PASS"] * 6)
        self.assertEqual(sr.select_rows(rows, "outInspLotStatusNm", "PASS", 2, 2)[0], [1, 2])
        self.assertEqual(len(sr.select_rows(rows, "outInspLotStatusNm", "PASS", 1, 0)[0]), 6)

    def test_asking_for_more_than_exists_returns_what_exists(self):
        rows = rows_of(["PASS"] * 3)
        self.assertEqual(len(sr.select_rows(rows, "outInspLotStatusNm", "PASS", 2, 50)[0]), 2)

    def test_blank_status_is_not_clickable(self):
        rows = rows_of(["PASS", "", "PASS"])
        self.assertEqual(sr.select_rows(rows, "outInspLotStatusNm", "PASS", 1, 0), ([0, 2], 1))

    def test_a_screen_without_the_status_column_picks_every_row(self):
        rows = [{"planYmd": "1"}] * 3
        self.assertEqual(sr.select_rows(rows, "outInspLotStatusNm", "PASS", 1, 0)[0], [0, 1, 2])

    def test_empty_and_past_the_end(self):
        self.assertEqual(sr.select_rows([], "x", "PASS", 1, 5), ([], 0))
        self.assertEqual(sr.select_rows(rows_of(["PASS"]), "outInspLotStatusNm", "PASS", 9, 0), ([], 0))


class TheDialogBoxes(unittest.TestCase):
    STATES = [{"name": "grdPackInspArtList", "on": True}, {"name": "grdDtlInspArtList", "on": True}]

    def test_default_open_state_needs_only_grid_two_unticked(self):
        clicks, missing = sr.plan_dialog_clicks(self.STATES, ["grdPackInspArtList"])
        self.assertEqual((clicks, missing), (["grdDtlInspArtList"], []))

    def test_already_right_needs_no_click(self):
        states = [{"name": "grdPackInspArtList", "on": True}, {"name": "grdDtlInspArtList", "on": False}]
        self.assertEqual(sr.plan_dialog_clicks(states, ["grdPackInspArtList"]), ([], []))

    def test_a_wanted_box_that_is_off_gets_ticked_and_case_is_ignored(self):
        states = [{"name": "grdPackInspArtList", "on": False}, {"name": "grdDtlInspArtList", "on": False}]
        clicks, _ = sr.plan_dialog_clicks(states, ["GRDPACKINSPARTLIST", "grdDtlInspArtList"])
        self.assertEqual(clicks, ["grdPackInspArtList", "grdDtlInspArtList"])

    def test_an_unknown_grid_is_reported_not_guessed(self):
        clicks, missing = sr.plan_dialog_clicks(self.STATES, ["nope"])
        self.assertEqual(missing, ["nope"])


class WhereAClickMayLand(unittest.TestCase):
    GRID = {"left": 269, "right": 1800, "top": 211, "bottom": 523, "head_bottom": 251}

    def cell(self, y, x=980):
        return {"x": x, "y": y}

    def test_a_row_inside_the_body_is_clickable(self):
        self.assertTrue(sr.visible_in_grid(self.cell(300), self.GRID))

    def test_the_last_row_at_the_bottom_edge_is_clickable(self):
        self.assertTrue(sr.visible_in_grid(self.cell(510), self.GRID))       # live: row 1074

    def test_rows_drawn_below_the_grid_are_not(self):
        self.assertFalse(sr.visible_in_grid(self.cell(551), self.GRID))      # live: row 13 of 14 drawn
        self.assertFalse(sr.visible_in_grid(self.cell(575), self.GRID))

    def test_a_row_under_the_header_is_not(self):
        self.assertFalse(sr.visible_in_grid(self.cell(240), self.GRID))

    def test_behind_the_scroll_bar_is_not(self):
        self.assertFalse(sr.visible_in_grid(self.cell(300, x=1795), self.GRID))


class FileNames(unittest.TestCase):
    def test_pattern_and_illegal_characters(self):
        self.assertEqual(sr.file_stem("{plan}_{model}_{lot}", "20260901", "UA65/M:7", "L1"),
                         "20260901_UA65_M_7_L1")
        self.assertEqual(sr.safe_name("  a b  "), "a_b")
        self.assertEqual(sr.safe_name("..."), "_")

    def test_an_existing_or_taken_name_is_never_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "a.xlsx"), "w").close()
            first = sr.unique_path(folder, "a")
            self.assertEqual(os.path.basename(first), "a-2.xlsx")
            second = sr.unique_path(folder, "a", taken={"a-2.xlsx"})
            self.assertEqual(os.path.basename(second), "a-3.xlsx")
            self.assertEqual(os.path.basename(sr.unique_path(folder, "b")), "b.xlsx")

    def test_eta(self):
        self.assertEqual(sr.eta_seconds(0, 10, 5), 0)
        self.assertEqual(sr.eta_seconds(5, 10, 50), 50)
        self.assertEqual(sr.eta_seconds(10, 10, 99), 0)


class StopPauseAndWaits(unittest.TestCase):
    def runner(self):
        return sr.Runner(sr.Settings(), log=lambda _m: None)

    def test_stop_raises_at_the_next_check(self):
        r = self.runner()
        r._check()
        r.request_stop()
        with self.assertRaises(sr.StopRequested):
            r._check()

    def test_a_wait_returns_the_value_and_honours_stop(self):
        r = self.runner()
        self.assertEqual(r._wait(lambda: "x", 1), "x")
        self.assertIsNone(r._wait(lambda: None, 0.3, delay=0.05))
        threading.Timer(0.2, r.request_stop).start()
        started = time.time()
        with self.assertRaises(sr.StopRequested):
            r._wait(lambda: None, 30, delay=0.05)
        self.assertLess(time.time() - started, 2)

    def test_pause_holds_until_resumed_and_stop_breaks_a_pause(self):
        r = self.runner()
        r.pause()
        released = []
        t = threading.Thread(target=lambda: (r._check(), released.append(1)))
        t.start()
        time.sleep(0.4)
        self.assertEqual(released, [])
        r.resume()
        t.join(2)
        self.assertEqual(released, [1])
        r.pause()
        err = []

        def blocked():
            try:
                r._check()
            except sr.StopRequested:
                err.append("stopped")
        t = threading.Thread(target=blocked)
        t.start()
        time.sleep(0.3)
        r.request_stop()
        t.join(2)
        self.assertEqual(err, ["stopped"])

    def test_a_sleep_is_interrupted_by_stop(self):
        r = self.runner()
        threading.Timer(0.2, r.request_stop).start()
        started = time.time()
        with self.assertRaises(sr.StopRequested):
            r._sleep(30)
        self.assertLess(time.time() - started, 2)


class TheRunLoop(unittest.TestCase):
    """The loop around export_row, with the browser side replaced."""

    def make(self, statuses, **kw):
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        s = sr.Settings(out_dir=folder, **kw)
        r = sr.Runner(s, log=lambda _m: None)
        r.rows = rows_of(statuses)
        r.exported = []

        def fake_export(index, taken):
            d = r.rows[index]
            stem = sr.file_stem(s.name_pattern, d["planYmd"], d["modelCode"], d["outInspLotNo"])
            path = sr.unique_path(folder, stem, taken=taken)
            with open(path, "wb") as fh:
                fh.write(b"x" * 1000)
            r.exported.append(index + 1)
            return path, 1000
        r.export_row = fake_export
        patches = (mock.patch.object(sr.gmes_common, "screenshot_on_failure"),
                   mock.patch.object(sr.gmes_common, "close_child_popups"),
                   mock.patch.object(sr.shutil, "disk_usage",
                                     return_value=mock.Mock(free=10 ** 12)))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        r._recover = lambda: None
        return r, folder

    @staticmethod
    def lines(summary):
        with open(summary["csv"], newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def test_only_pass_rows_in_range_and_a_result_list_is_written(self):
        r, _ = self.make(["PASS", "In progress", "PASS", "PASS"], count=2, start_row=1, link_value="PASS")
        summary = r.run()
        self.assertEqual(r.exported, [1, 3])
        self.assertEqual((summary["ok"], summary["failed"], summary["planned"]), (2, 0, 2))
        self.assertEqual([x["status"] for x in self.lines(summary)], ["ok", "ok"])

    def test_more_rows_than_exist_exports_what_exists(self):
        r, _ = self.make(["PASS", "PASS"], count=50)
        self.assertEqual(r.run()["ok"], 2)

    def test_nothing_to_export_is_said_not_crashed(self):
        r, _ = self.make(["In progress"], count=5, link_value="PASS")
        summary = r.run()
        self.assertEqual((summary["ok"], summary["planned"], summary["fatal"]), (0, 0, ""))

    def test_second_run_skips_existing_files(self):
        r, folder = self.make(["PASS", "PASS", "PASS"])
        r.run()
        r2, _ = self.make(["PASS", "PASS", "PASS"])
        r2.s.out_dir = folder
        r2.exported = []
        summary = r2.run()
        self.assertEqual((summary["ok"], summary["skipped"]), (0, 3))
        self.assertEqual(r2.exported, [])

    def test_skip_existing_off_never_overwrites(self):
        r, folder = self.make(["PASS"], skip_existing=False)
        r.run()
        r2, _ = self.make(["PASS"], skip_existing=False)
        r2.s.out_dir = folder
        r2.export_row = r.export_row
        r2.run()
        self.assertEqual(len([n for n in os.listdir(folder) if n.endswith(".xlsx")]), 2)

    def test_stop_after_the_second_row(self):
        r, _ = self.make(["PASS"] * 6)
        original = r.export_row

        def stopping(index, taken):
            out = original(index, taken)
            if len(r.exported) == 2:
                r.request_stop()
            return out
        r.export_row = stopping
        summary = r.run()
        self.assertTrue(summary["stopped"])
        self.assertEqual(r.exported, [1, 2])
        self.assertEqual([x["status"] for x in self.lines(summary)], ["ok", "ok"])

    def test_stop_mid_row_leaves_one_stopped_line_and_no_file(self):
        r, folder = self.make(["PASS"] * 3)

        def stopped_mid_row(index, taken):
            raise sr.StopRequested()
        r.export_row = stopped_mid_row
        summary = r.run()
        self.assertTrue(summary["stopped"])
        self.assertEqual([x["status"] for x in self.lines(summary)], ["stopped"])
        self.assertEqual([n for n in os.listdir(folder) if n.endswith(".xlsx")], [])

    def test_on_error_stop_stops_at_the_first_failure(self):
        r, _ = self.make(["PASS"] * 4, on_error="stop", retries=1)
        calls = []

        def boom(index, taken):
            calls.append(index)
            raise RuntimeError("popup did not open")
        r.export_row = boom
        summary = r.run()
        self.assertEqual(len(calls), 2)                    # one try + one retry, then it stops
        self.assertIn("failed", summary["fatal"])
        self.assertEqual(summary["failed"], 1)

    def test_on_error_skip_continues_and_stops_after_max_errors_in_a_row(self):
        r, _ = self.make(["PASS"] * 6, on_error="skip", max_errors=2, retries=0)
        good = r.export_row

        def flaky(index, taken):
            if index in (1, 2):
                raise RuntimeError("x")
            return good(index, taken)
        r.export_row = flaky
        summary = r.run()
        self.assertEqual(r.exported, [1])
        self.assertEqual(summary["failed"], 2)
        self.assertIn("in a row", summary["fatal"])

    def test_a_single_failure_with_skip_does_not_stop_the_run(self):
        r, _ = self.make(["PASS"] * 4, on_error="skip", max_errors=2, retries=0)
        good = r.export_row

        def flaky(index, taken):
            if index == 1:
                raise RuntimeError("x")
            return good(index, taken)
        r.export_row = flaky
        summary = r.run()
        self.assertEqual((summary["ok"], summary["failed"], summary["fatal"]), (3, 1, ""))

    def test_a_fatal_error_is_never_retried_and_is_reported(self):
        r, _ = self.make(["PASS"] * 3, retries=3)
        calls = []

        def gone(index, taken):
            calls.append(index)
            raise sr.FatalError("browser gone")
        r.export_row = gone
        summary = r.run()
        self.assertEqual(len(calls), 1)
        self.assertEqual(summary["fatal"], "browser gone")
        self.assertEqual([x["status"] for x in self.lines(summary)], ["aborted"])

    def test_too_little_disk_space_refuses_before_the_first_click(self):
        r, _ = self.make(["PASS"] * 3)
        with mock.patch.object(sr.shutil, "disk_usage", return_value=mock.Mock(free=1000)):
            summary = r.run()
        self.assertIn("free", summary["fatal"])
        self.assertEqual(r.exported, [])

    def test_progress_is_reported_for_every_row(self):
        r, _ = self.make(["PASS"] * 3)
        seen = []
        r.progress = lambda **kw: seen.append((kw["done"], kw["total"]))
        r.run()
        self.assertEqual(seen, [(1, 3), (2, 3), (3, 3)])

    def test_duplicate_names_in_one_run_do_not_overwrite(self):
        r, folder = self.make(["PASS", "PASS"], name_pattern="{plan}")
        r.run()
        self.assertEqual(sorted(n for n in os.listdir(folder) if n.endswith(".xlsx")),
                         ["20260901-2.xlsx", "20260901.xlsx"])


class NamedPeriods(unittest.TestCase):
    """This month / last month / today / yesterday follow the calendar."""

    def test_current_and_previous(self):
        from datetime import datetime
        now = datetime(2026, 10, 1)
        self.assertEqual(sr.resolve_period("Monthly", "", now), "202610")
        self.assertEqual(sr.resolve_period("Monthly", "previous", now), "202609")
        self.assertEqual(sr.resolve_period("Daily", "current", now), "20261001")
        self.assertEqual(sr.resolve_period("Daily", "previous", now), "20260930")
        self.assertEqual(sr.resolve_period("Monthly", "previous", datetime(2026, 1, 15)), "202512")
        self.assertEqual(sr.resolve_period("Monthly", "202607", now), "202607")

    def test_named_periods_validate(self):
        self.assertEqual(sr.validate_settings(sr.Settings(period="previous")), [])
        self.assertEqual(sr.validate_settings(sr.Settings(period_mode="Daily", period="previous")), [])


class EveryStatusByDefault(unittest.TestCase):
    """Owner, 2026-09-30: export In progress, Outgoing Revoke and anything else too."""

    def test_the_default_takes_every_row(self):
        rows = rows_of(["PASS", "In progress", "Outgoing Revoke", "", "PASS"])
        s = sr.Settings()
        self.assertEqual(s.link_value, "")
        self.assertEqual(sr.select_rows(rows, s.status_column, s.link_value, 1, 0), ([0, 1, 2, 3, 4], 0))
        self.assertEqual(sr.count_link_rows(rows, s.status_column, s.link_value), 5)

    def test_a_status_still_narrows_when_asked(self):
        rows = rows_of(["PASS", "In progress"])
        self.assertEqual(sr.select_rows(rows, "outInspLotStatusNm", "In progress", 1, 0), ([1], 1))

    def test_version_1_settings_that_said_pass_become_every_status(self):
        import samir_app
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        path = os.path.join(folder, "settings.json")
        import json
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"link_value": "PASS", "start_row": 6}, fh)
        with mock.patch.object(samir_app, "SETTINGS_FILE", path):
            s, _browser = samir_app.load_saved()
            self.assertEqual((s.link_value, s.start_row), ("", 6))
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"link_value": "PASS", "settings_version": 2}, fh)
            self.assertEqual(samir_app.load_saved()[0].link_value, "PASS")   # a v2 choice is kept


class LeftAloneCountsOnlyTheSpanCovered(unittest.TestCase):
    def test_non_link_rows_after_the_last_picked_row_are_not_counted(self):
        rows = rows_of(["PASS", "In progress", "PASS", "PASS", "In progress", "In progress"])
        picked, other = sr.select_rows(rows, "outInspLotStatusNm", "PASS", 1, 2)
        self.assertEqual((picked, other), ([0, 2], 1))

    def test_all_remaining_counts_to_the_end(self):
        rows = rows_of(["PASS", "In progress", "PASS", "In progress"])
        self.assertEqual(sr.select_rows(rows, "outInspLotStatusNm", "PASS", 1, 0), ([0, 2], 2))

    def test_asking_for_more_than_exists_counts_to_the_end(self):
        rows = rows_of(["PASS", "In progress"])
        self.assertEqual(sr.select_rows(rows, "outInspLotStatusNm", "PASS", 1, 9), ([0], 1))

    def test_count_link_rows(self):
        self.assertEqual(sr.count_link_rows(rows_of(["PASS", "", "PASS"]), "outInspLotStatusNm", "PASS"), 2)


class ARetryThatWorksIsASuccess(unittest.TestCase):
    make = TheRunLoop.make
    lines = staticmethod(TheRunLoop.lines)

    def test_first_attempt_fails_second_works(self):
        r, _ = self.make(["PASS", "PASS"], on_error="stop", retries=1)
        good, calls = r.export_row, []

        def once_flaky(index, taken):
            calls.append(index)
            if calls.count(index) == 1 and index == 0:
                raise RuntimeError("dialog did not appear")
            return good(index, taken)
        r.export_row = once_flaky
        summary = r.run()
        self.assertEqual((summary["ok"], summary["failed"], summary["fatal"]), (2, 0, ""))
        self.assertEqual([x["status"] for x in self.lines(summary)], ["ok", "ok"])

    def test_the_time_left_ignores_skipped_rows(self):
        self.assertEqual(sr.eta_seconds(2, 10, 20.0), 80)
        self.assertEqual(sr.eta_seconds(0, 10, 0.0), 0)


class AccountAndBrowser(unittest.TestCase):
    """samir_setup: the login goes only into the engine's DPAPI store; a browser
    choice only sets the engine's own variables, and never re-copies over a profile."""

    @classmethod
    def setUpClass(cls):
        import samir_setup
        cls.setup = samir_setup

    def test_automatic_leaves_the_engine_as_it_is(self):
        plan = self.setup.plan_browser_env("auto", "chrome", r"C:\root")
        self.assertEqual(plan, {k: None for k in self.setup.ENV_KEYS})

    def test_the_recorded_browser_keeps_the_standard_profile(self):
        for recorded in (None, "edge"):
            plan = self.setup.plan_browser_env("edge", recorded, r"C:\root")
            self.assertEqual(plan["GMES_BROWSER"], "edge")
            self.assertIsNone(plan["GMES_PROFILE_DIR"])
            self.assertIsNone(plan["GMES_BROWSER_STATE"])

    def test_another_browser_gets_its_own_profile_and_record(self):
        plan = self.setup.plan_browser_env("edge", "chrome", r"C:\root")
        self.assertEqual(plan["GMES_PROFILE_DIR"], os.path.join(r"C:\root", "profiles", "samir-edge"))
        self.assertEqual(plan["GMES_BROWSER_STATE"], os.path.join(r"C:\root", "samir-browser-edge.json"))
        with self.assertRaises(ValueError):
            self.setup.plan_browser_env("firefox", None, r"C:\root")

    def test_apply_then_auto_restores_the_environment(self):
        before = {k: os.environ.get(k) for k in self.setup.ENV_KEYS}
        try:
            self.setup.apply_browser_choice("edge")
            self.assertEqual(os.environ.get("GMES_BROWSER"), "edge")
            self.setup.apply_browser_choice("auto")
            self.assertEqual({k: os.environ.get(k) for k in self.setup.ENV_KEYS}, before)
        finally:
            self.setup._restore_original_env()

    def test_typed_login_is_checked(self):
        check = self.setup.check_new_login
        self.assertTrue(check("", "pw", "pw"))
        self.assertTrue(check("a b", "pw", "pw"))
        self.assertTrue(check("user", "", ""))
        self.assertTrue(check("user", "pw", "pW"))
        self.assertTrue(check("user", " pw", " pw"))
        self.assertEqual(check(" user ", "pw", "pw"), [])

    def test_save_login_round_trips_through_dpapi_in_a_temporary_store(self):
        import gmes_credentials
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        temp_store = os.path.join(folder, "credentials.dat")
        with mock.patch.object(gmes_credentials, "STORE_DIR", folder), \
                mock.patch.object(gmes_credentials, "STORE_PATH", temp_store):
            self.assertEqual(self.setup.saved_login()[0], None)
            self.assertEqual(self.setup.save_login(" samir.x ", "S3cret!", "S3cret!"), "samir.x")
            self.assertEqual(self.setup.saved_login(), ("samir.x", ""))
            with open(temp_store, "rb") as fh:
                self.assertNotIn(b"S3cret!", fh.read())                  # encrypted on disk
            with self.assertRaises(ValueError):
                self.setup.save_login("samir.x", "a", "b")
            self.assertEqual(self.setup.saved_login()[0], "samir.x")   # a bad retype changes nothing

    def test_a_login_that_does_not_read_back_is_reported(self):
        import gmes_credentials
        with mock.patch.object(gmes_credentials, "save"), \
                mock.patch.object(gmes_credentials, "load", return_value=(None, None)):
            with self.assertRaises(ValueError) as caught:
                self.setup.save_login("samir.x", "pw", "pw")
        self.assertIn("could not be read back", str(caught.exception))

    def test_saved_login_never_returns_the_password(self):
        import gmes_credentials
        with mock.patch.object(gmes_credentials, "load", return_value=("u", "secret")):
            self.assertNotIn("secret", repr(self.setup.saved_login()))

    def test_describe_browsers_never_raises(self):
        import gmes_browsers
        with mock.patch.object(gmes_browsers, "default_browser_key", side_effect=OSError("registry")):
            info = self.setup.describe_browsers()
        self.assertIn("registry", info["error"])
        self.assertIsInstance(self.setup.setup_sentence(info), str)

    def test_setup_sentence(self):
        import gmes_browsers
        machine = gmes_browsers.machine_id()
        done = {"state": {"completed": True, "machine": machine, "browser": "edge", "strategy": "copied",
                          "source": {"profile_name": "Work"}, "onboarded_at": "2026-09-30"},
                "same_machine": True}
        self.assertIn("Microsoft Edge", self.setup.setup_sentence(done))
        self.assertIn("'Work'", self.setup.setup_sentence(done))
        todo = {"state": {}, "next_copy": {"label": "Google Chrome", "profile": "Person 1"}}
        self.assertIn("first Connect", self.setup.setup_sentence(todo))
        self.assertIn("empty profile", self.setup.setup_sentence({"state": {}}))


class PlainWordsInTheLog(unittest.TestCase):
    def test_separators_and_developer_wording_are_left_out(self):
        got = []
        r = sr.Runner(sr.Settings(), log=got.append)
        r._engine_log("\n" + "=" * 70 + "\nQ321KUM00\n" + "=" * 70)
        r._engine_log("warning  : fromDt was typed with --set, so the result was NOT checked")
        r._engine_log("inquiry  : 1074 rows in 7.5s")
        self.assertEqual(got, ["  | Q321KUM00", "  | inquiry  : 1074 rows in 7.5s"])


class FirstRunCopyIsItsOwnStep(unittest.TestCase):
    def test_a_locked_browser_profile_becomes_a_plain_instruction(self):
        import gmes_browsers
        r = sr.Runner(sr.Settings(), log=lambda _m: None)
        with mock.patch.object(gmes_browsers, "recorded_profile_dir", return_value=None), \
                mock.patch.object(gmes_browsers, "ensure_bootstrapped",
                                  side_effect=gmes_browsers.ProfileLocked("Edge holds it")):
            with self.assertRaises(sr.FatalError) as caught:
                r.prepare_browser_profile()
        self.assertIn("Close every window", str(caught.exception))

    def test_nothing_is_done_once_the_copy_exists(self):
        import gmes_browsers
        r = sr.Runner(sr.Settings(), log=lambda _m: None)
        with mock.patch.object(gmes_browsers, "recorded_profile_dir", return_value=r"C:\x"), \
                mock.patch.object(gmes_browsers, "ensure_bootstrapped") as boot:
            self.assertIsNone(r.prepare_browser_profile())
        boot.assert_not_called()


def _all_widgets(root):
    out, todo = [], [root]
    while todo:
        w = todo.pop()
        out.append(w)
        todo.extend(w.winfo_children())
    return out


class TheWindow(unittest.TestCase):
    """The window itself: builds, fits, and routes engine output into the log."""

    def test_engine_output_arrives_as_whole_lines(self):
        import samir_app
        got = []
        sink = samir_app.OutputSink(None)
        sink.target = got.append
        sink.write("Signing in as 'x' ")
        sink.write("via AD SSO...\nSigned in as 'Mohamed'.\n")
        self.assertEqual(got, ["Signing in as 'x' via AD SSO...", "Signed in as 'Mohamed'."])

    def test_log_colours(self):
        import samir_app
        self.assertEqual(samir_app.classify("row 12: OK  a.xlsx"), "ok")
        self.assertEqual(samir_app.classify("PROBLEM: sign-in failed"), "err")
        self.assertEqual(samir_app.classify("note: something"), "warn")
        self.assertEqual(samir_app.fmt_eta(3725), "1h 02m")
        self.assertEqual(samir_app.fmt_eta(0), "-")
        self.assertEqual(samir_app.pretty_period("Monthly", "202609"), "2026-09")

    def make_app(self):
        import samir_app
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        for name, value in (("LOG_FILE", os.path.join(folder, "test.log")),
                            ("SETTINGS_FILE", os.path.join(folder, "settings.json"))):
            p = mock.patch.object(samir_app, name, value)     # never the person's own files
            p.start()
            self.addCleanup(p.stop)
        try:
            app = samir_app.App()
        except Exception as e:                               # noqa: BLE001 - no display
            self.skipTest(f"no display: {e}")
        fallback = app.sink.fallback

        def done():
            sys.stdout = sys.stderr = fallback or sys.__stdout__
            app.destroy()
        self.addCleanup(done)
        return app

    def test_every_message_the_workers_send_has_a_handler(self):
        import re as _re
        import samir_app
        with open(samir_app.__file__, encoding="utf-8") as fh:
            source = fh.read()
        sent = set(_re.findall(r'_post\("(\w+)"', source)) | {"failed"}
        missing = [k for k in sent if not hasattr(samir_app.App, f"_on_{k}_msg")]
        self.assertEqual(missing, [])

    def test_an_engine_line_reaches_the_log_and_a_bad_message_does_not_stop_the_pump(self):
        app = self.make_app()
        app._post("no_such_kind")
        app.sink.write("Signed in as 'Test Person'.\n")
        app._pump()
        text = app.log_text.get("1.0", "end")
        self.assertIn("Signed in as 'Test Person'", text)
        self.assertIn("display problem", text)
        self.assertEqual(app.lbl_user.cget("text"), "Signed in as Test Person")

    def test_the_mouse_wheel_never_changes_a_filter_or_a_count(self):
        # HISTORY.md Phase 114: in ttk the wheel over a combo/spin box changes its
        # value; scrolling past "Organization" changed the division and dropped
        # the loaded list.
        app = self.make_app()
        app.update()
        combo = next(w for w in _all_widgets(app) if isinstance(w, ttk.Combobox)
                     and str(w.cget("textvariable")) == str(app.v_div))
        spin = next(w for w in _all_widgets(app) if isinstance(w, ttk.Spinbox)
                    and str(w.cget("textvariable")) == str(app.v_count))
        app.v_div.set("MAIN Part")
        app.v_count.set("20")
        for widget in (combo, spin):
            for delta in (-120, 120, -120):
                widget.event_generate("<MouseWheel>", delta=delta)
        app.update()
        self.assertEqual((app.v_div.get(), app.v_count.get()), ("MAIN Part", "20"))

    def test_the_window_builds_and_every_button_starts_in_the_right_state(self):
        app = self.make_app()
        if True:
            app.update()
            self.assertTrue(app.btn_load.enabled)
            for b in (app.btn_start, app.btn_pause, app.btn_stop, app.btn_now):
                self.assertFalse(b.enabled)
            app.show_tab("account")
            app.update()
            app.v_all.set(False)
            app.v_count.set("abc")
            with self.assertRaises(ValueError):
                app._collect()
            app.v_count.set("5")
            app.v_which.set("custom")
            app.v_custom.set("")
            with self.assertRaises(ValueError):
                app._collect()


if __name__ == "__main__":
    unittest.main()
