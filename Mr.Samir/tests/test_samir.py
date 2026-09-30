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
        r, _ = self.make(["PASS", "In progress", "PASS", "PASS"], count=2, start_row=1)
        summary = r.run()
        self.assertEqual(r.exported, [1, 3])
        self.assertEqual((summary["ok"], summary["failed"], summary["planned"]), (2, 0, 2))
        self.assertEqual([x["status"] for x in self.lines(summary)], ["ok", "ok"])

    def test_more_rows_than_exist_exports_what_exists(self):
        r, _ = self.make(["PASS", "PASS"], count=50)
        self.assertEqual(r.run()["ok"], 2)

    def test_nothing_to_export_is_said_not_crashed(self):
        r, _ = self.make(["In progress"], count=5)
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


if __name__ == "__main__":
    unittest.main()
