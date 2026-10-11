"""Offline tests for GMES Automation (GMES/). No browser, no network, no G-MES.

    python GMES/tests/test_gmes_app.py

Everything runs against a temporary data folder (GMES_APP_DATA), so a test never
touches the person's recordings, logs or settings. They guard the DECISIONS - the
record check, plans, schedules, the session's refusals - not the browser half,
which is proven live (HISTORY.md).
"""
import inspect
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

DATA = tempfile.mkdtemp(prefix="gmes-app-test-")
os.environ["GMES_APP_DATA"] = DATA
# Two guards against a test syncing its fake recordings into the person's real ones:
# app_env never pairs a GMES_APP_DATA folder with the project, and this switches the
# twin off outright (CLAUDE.md 0a).
os.environ["GMES_TWIN"] = "off"
os.environ["GMES_DOSSIER"] = "off"   # a mocked run never logs into the real screen library (Phase 131)
os.environ["GMES_SIGNIN_LEDGER"] = os.path.join(__import__("tempfile").mkdtemp(prefix="gmes-ledger-test-"), "ledger.jsonl")   # Phase 132
os.environ["GMES_TWIN_CLI_ROOT"] = tempfile.mkdtemp(prefix="gmes-twin-test-")
APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
sys.path.insert(0, APP)

import app_env                        # noqa: E402
import service                        # noqa: E402
import sync_engine                    # noqa: E402
import gmes_batch                     # noqa: E402
import gmes_core                      # noqa: E402
import gmes_profile                   # noqa: E402
import gmes_schedule                  # noqa: E402


_guard = None


def setUpModule():
    """No test may reach the real Task Scheduler - one did, under a mutation check, and
    registered a real task (HISTORY.md 117). Tests that need it patch it themselves."""
    global _guard
    _guard = mock.patch.object(gmes_schedule, "_run_powershell",
                               side_effect=AssertionError("a test reached the real Task Scheduler"))
    _guard.start()


def tearDownModule():
    _guard.stop()


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def spec(**kw):
    base = dict(code="P1112UM00", division="VD", date_from="20260929", date_to="20260929",
                verify="planYmd", export="both")
    base.update(kw)
    code = base.pop("code")
    return service.build_spec(code, **base)


def files(n=1, size=2000):
    out = []
    for i in range(n):
        path = os.path.join(DATA, f"f{i}_{size}.bin")
        with open(path, "wb") as fh:
            fh.write(b"x" * size)
        out.append(path)
    return out


def good_rec(**kw):
    rec = {"ok": True, "screen": "P1112UM00", "title": "Production Plan", "division": "VD",
           "applied": {}, "rows": 64, "grid": "grdMain -> dsMain", "files": files(2),
           "csv_rows": 64, "verified": {"planYmd": ["20260929"]}, "warnings": [],
           "profile": "P1112UM00.json"}
    rec.update(kw)
    return rec


class OneImplementationForBothFrontEnds(unittest.TestCase):
    """The record check, Row export and the twin sync are ENGINE code since HISTORY.md
    Phase 123: the window and GMES_Workflow.bat run the very same functions."""

    def test_the_record_check_is_the_engines(self):
        import gmes_recordcheck as rc
        for name in ("judge", "verdict", "build_spec", "check_spec", "month_bounds", "typed_period",
                     "date_spread", "confirm_and_rejudge", "certificates", "plain", "Stopped", "Problem"):
            with self.subTest(name=name):
                self.assertIs(getattr(service, name), getattr(rc, name))

    def test_certificates_and_confirmations_live_in_the_apps_data_folder(self):
        import gmes_recordcheck as rc
        self.assertEqual(os.path.normcase(rc.cert_dir()), os.path.normcase(os.path.join(DATA, "certificates")))
        self.assertEqual(os.path.normcase(rc.confirm_path()),
                         os.path.normcase(os.path.join(DATA, service.CONFIRM_FILE)))

    def test_a_test_data_folder_is_never_paired_with_the_project(self):
        self.assertTrue(service.gmes_twin.CONFIGURED)
        self.assertIsNone(service.gmes_twin.CLI_ROOT)
        with mock.patch.dict(os.environ, {"GMES_TWIN": ""}):
            self.assertIsNone(service.gmes_twin.pair())

    def test_the_app_finds_the_project_it_sits_in(self):
        self.assertTrue(service.gmes_twin.is_project_root(app_env.project_root()))


class TheEngineIsCopiedNotRewritten(unittest.TestCase):
    def test_every_copy_matches_the_project(self):
        self.assertEqual(sync_engine.check(), [])

    def test_a_changed_copy_is_reported(self):
        target = os.path.join(sync_engine.ENGINE, "gmes_redact.py")
        with open(target, "rb") as fh:
            original = fh.read()
        try:
            with open(target, "ab") as fh:
                fh.write(b"\n# changed\n")
            self.assertTrue(any("gmes_redact" in p for p in sync_engine.check()))
        finally:
            with open(target, "wb") as fh:
                fh.write(original)

    def test_the_closure_holds_batches_and_schedules(self):
        for name in ("gmes_core", "gmes_batch", "gmes_schedule", "gmes_library", "cdp_common"):
            self.assertIn(name, sync_engine.closure())


class EverythingLandsInTheAppsDataFolder(unittest.TestCase):
    def test_engine_paths_point_into_data(self):
        for path in (gmes_core.OUTPUT_DIR, gmes_profile.SCREENS_DIR, gmes_batch.BATCH_DIR,
                     gmes_batch.REPORT_DIR, gmes_schedule.SCHEDULE_DIR):
            self.assertTrue(os.path.abspath(path).startswith(os.path.abspath(DATA)), path)

    def test_schedules_never_collide_with_the_cli_tools_tasks(self):
        self.assertEqual(gmes_schedule.PREFIX, "GMES_App_")
        self.assertEqual(gmes_schedule.task_name("morning"), "GMES_App_morning")

    def test_shipped_structures_are_found(self):
        self.assertTrue(os.path.isdir(gmes_profile.SHIPPED_DIR))
        self.assertTrue(any(not p.get("learned") for p in gmes_profile.known()))


class AServerCopyStartsWithTheSeed(unittest.TestCase):
    """make_package.bat server: the project's recordings, batches and record checks of
    every site go beside the .exe as seed\\, and the window syncs with it by the twin's
    rules - so nothing the server learned is replaced (HISTORY.md Phase 130)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gmes-seed-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, *parts, data):
        path = os.path.join(self.tmp, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path

    def read(self, *parts):
        with open(os.path.join(self.tmp, *parts), encoding="utf-8") as fh:
            return json.load(fh)

    def test_the_window_pairs_with_the_project_else_the_seed(self):
        alone = os.path.join(self.tmp, "GMES")
        os.makedirs(os.path.join(alone, "seed"))
        with mock.patch.object(app_env, "base_dir", return_value=alone):
            self.assertIsNone(app_env.twin_root())                   # an empty seed folder is nothing
            os.makedirs(os.path.join(alone, "seed", "screens"))
            self.assertEqual(app_env.twin_root(), os.path.join(alone, "seed"))
        with mock.patch.object(app_env, "project_root", return_value="P"), \
             mock.patch.object(app_env, "seed_root", return_value="S"):
            self.assertEqual(app_env.twin_root(), "P")               # beside the project: the project

    def test_the_seed_carries_both_sites_and_only_portable_pins(self):
        import make_seed
        proj = os.path.join(self.tmp, "proj")
        rec = {"screen": "A1234UM00", "learned": "2026-10-01 10:00:00", "output_dir": "D:\\WORK\\x",
               "export": "csv"}
        self.write("proj", "screens", "A1234UM00.json", data=rec)
        self.write("proj", "screens", "batches", "night.json", data={"name": "night", "screens": ["A1234UM00"]})
        self.write("proj", "screens", "batches", "Test.json", data={"name": "Test", "screens": []})
        self.write("proj", "screens", "certificates", "A1234UM00_20261011_101010.json", data={"ok": True})
        self.write("proj", "screens", "confirmations.json", data={})
        self.write("proj", "sites", "hq", "screens", "B2222WM01.json",
                   data={"screen": "B2222WM01", "learned": "2026-10-02", "output_dir": "\\\\srv\\share\\AX",
                         "distribute_to": ["\\\\srv\\b", "C:\\Users\\me\\x"]})
        self.write("proj", "sites", "hq", "screens", "batches", "weekly_hq.json",
                   data={"name": "weekly_hq", "screens": ["B2222WM01"], "date": "lastweek"})
        self.write("proj", "logs", "batches", "batch_20261011_1.json", data={})          # never carried
        self.write("proj", "screens", "library", "A1234UM00 - Test", "notes.md", data="learned")
        for shot in ("20261011_080000_result.png", "20261011_090000_record-result.png"):
            self.write("proj", "screens", "library", "A1234UM00 - Test", "screenshots", shot, data="png")
        said = []
        seed = os.path.join(self.tmp, "seed")
        summary = make_seed.build(proj, seed, log=said.append, leave_out={("seeg", "batches", "test.json")})
        self.assertEqual(summary["seeg"], {"recordings": 1, "batches": 1, "certificates": 1, "confirmations": 1, "library": 1})
        self.assertEqual(summary["hq"], {"recordings": 1, "batches": 1, "certificates": 0, "library": 0})
        lib = os.path.join(seed, "screens", "library", "A1234UM00 - Test")
        self.assertTrue(os.path.isfile(os.path.join(lib, "notes.md")))
        self.assertEqual(os.listdir(os.path.join(lib, "screenshots")), ["20261011_090000_record-result.png"])   # not the daily run's
        mine = self.read("seed", "screens", "A1234UM00.json")
        self.assertNotIn("output_dir", mine)                         # a folder of this PC
        self.assertEqual(mine["export"], "csv")
        hq = self.read("seed", "sites", "hq", "screens", "B2222WM01.json")
        self.assertEqual(hq["output_dir"], "\\\\srv\\share\\AX")     # a share: the same from every PC
        self.assertEqual(hq["distribute_to"], ["\\\\srv\\b"])
        self.assertFalse(os.path.exists(os.path.join(seed, "screens", "batches", "Test.json")))
        self.assertFalse(os.path.exists(os.path.join(seed, "logs")))
        self.assertTrue(any("D:\\WORK\\x" in s for s in said))
        self.assertEqual(make_seed.conflicts(type("R", (), {"conflicts": [
            ("batches", "Test.json", "x"), ("batches", "w.json (hq)", "y")]})()),
            {("seeg", "batches", "test.json"), ("hq", "batches", "w.json")})

    def test_unzipped_inside_an_old_project_the_seed_still_arrives(self):
        # the server already holds an older project copy (10 Oct): a GMES folder inside it pairs with
        # that project - the seed beside the .exe is synced too, and the newer recording wins
        import gmes_twin
        proj, seed, data = (os.path.join(self.tmp, n) for n in ("proj", "seed", "data"))
        self.write("proj", "screens", "Q2241UM00.json", data={"screen": "Q2241UM00", "learned": "2026-10-01"})
        self.write("seed", "screens", "Q2241UM00.json", data={"screen": "Q2241UM00", "learned": "2026-10-11"})
        self.write("seed", "sites", "hq", "screens", "P1112WM01.json", data={"screen": "P1112WM01", "learned": "2026-10-11"})
        os.makedirs(data)
        with mock.patch.object(app_env, "project_root", return_value=proj), \
             mock.patch.object(app_env, "seed_root", return_value=seed):
            self.assertEqual(app_env.extra_twin_roots(), (seed,))
        with mock.patch.object(app_env, "project_root", return_value=None), \
             mock.patch.object(app_env, "seed_root", return_value=seed):
            self.assertEqual(app_env.extra_twin_roots(), ())                  # the seed is already the twin
        with mock.patch.dict(os.environ, {"GMES_TWIN": ""}), \
             mock.patch.multiple(gmes_twin, CONFIGURED=True, CLI_ROOT=proj, EXE_DATA=data, EXTRA_ROOTS=(seed,)):
            gmes_twin.sync(scheduled=lambda: [])
        self.assertEqual(self.read("data", "screens", "Q2241UM00.json")["learned"], "2026-10-11")
        self.assertEqual(self.read("data", "sites", "hq", "screens", "P1112WM01.json")["learned"], "2026-10-11")
        with mock.patch.dict(os.environ, {"GMES_TWIN": ""}), \
             mock.patch.multiple(gmes_twin, CONFIGURED=True, CLI_ROOT=proj, EXE_DATA=data, EXTRA_ROOTS=(seed,)):
            gmes_twin.sync(scheduled=lambda: [])                              # the next start or task
        self.assertEqual(self.read("proj", "screens", "Q2241UM00.json")["learned"], "2026-10-11")   # on to the project
        self.assertEqual(app_env.setup.__code__.co_names.count("extra_twin_roots"), 1)

    def test_a_server_keeps_what_it_learned(self):
        import gmes_twin
        seed, data = os.path.join(self.tmp, "seed"), os.path.join(self.tmp, "data")
        self.write("seed", "screens", "A1234UM00.json", data={"screen": "A1234UM00", "learned": "2026-10-01"})
        self.write("seed", "sites", "hq", "screens", "batches", "weekly_hq.json",
                   data={"name": "weekly_hq", "screens": ["B2222WM01"], "date": "lastweek"})
        self.write("seed", "sites", "hq", "screens", "B2222WM01.json", data={"screen": "B2222WM01", "learned": "1"})
        self.write("data", "sites", "hq", "screens", "batches", "weekly_hq.json",
                   data={"name": "weekly_hq", "screens": ["C3333UM00"], "date": "yesterday"})
        self.write("data", "screens", "Z9999UM00.json", data={"screen": "Z9999UM00", "learned": "2026-10-05"})
        report = gmes_twin.sync(cli_root=seed, exe_data=data, scheduled=lambda: [])
        self.assertEqual(self.read("data", "screens", "A1234UM00.json")["learned"], "2026-10-01")
        self.assertEqual(self.read("data", "sites", "hq", "screens", "B2222WM01.json")["learned"], "1")
        self.assertEqual(self.read("data", "sites", "hq", "screens", "batches", "weekly_hq.json")["date"],
                         "yesterday")                                 # the server's own batch: untouched
        self.assertTrue(any(k == "batches" and "weekly_hq" in n for k, n, _ in report.conflicts))
        self.assertTrue(os.path.isfile(os.path.join(data, "screens", "Z9999UM00.json")))


class TheScopeIsCheckedBeforeAnythingRuns(unittest.TestCase):
    def test_a_good_spec(self):
        self.assertEqual(service.check_spec(spec()), [])

    def test_codes(self):
        self.assertEqual(service.normalise_code(" p1112 um00 "), "P1112UM00")
        self.assertTrue(service.check_spec(spec(code="P1112")))
        # Real codes carry letters (Q321KUM00), so a letter O where a zero belongs
        # (Q321OWM00) cannot be told apart by shape - the catalogue lookup catches it.
        self.assertEqual(service.check_spec(spec(code="Q321KUM00")), [])
        self.assertTrue(service.check_spec(spec(code="Q321KUM0")))

    def test_dates(self):
        self.assertTrue(service.check_spec(spec(date_from="2026-09-29", date_to="2026-09-29")))
        self.assertTrue(service.check_spec(spec(date_from="20260930", date_to="20260929")))
        self.assertEqual(service.check_spec(spec(date_from="", date_to="", verify="")), [])
        # Phase 121: not a calendar day; and a bare month, which the engine never accepts
        # (it reaches the engine as the month's first and last day - month_bounds)
        self.assertTrue(any("real calendar" in p for p in
                            service.check_spec(spec(date_from="20261399", date_to="20261399"))))
        problems = service.check_spec(spec(date_from="20261001", date_to="202610"))
        self.assertTrue(any("YYYYMMDD" in p for p in problems))
        self.assertFalse(any("after the end" in p for p in problems))
        self.assertTrue(service.check_spec(spec(date_from="202609", date_to="202609")))

    def test_a_month_becomes_its_first_and_last_day(self):
        # Before: the Record page's Month sent '202610' and Verify refused every row
        # (20261005 is "not exactly the requested 202610").
        self.assertEqual(service.month_bounds("202610", "202610"), ("20261001", "20261031"))
        self.assertEqual(service.month_bounds("202602", ""), ("20260201", "20260228"))
        self.assertEqual(service.month_bounds("202812", "202902"), ("20281201", "20290228"))
        self.assertEqual(service.month_bounds("202402", "202402"), ("20240201", "20240229"))
        self.assertEqual(service.month_bounds("20261005", "20261005"), ("20261005", "20261005"))
        self.assertEqual(service.month_bounds("202613", "202613"), ("202613", "202613"))
        f, t = service.month_bounds("202609", "202609")
        self.assertEqual(service.check_spec(spec(date_from=f, date_to=t)), [])

    def test_a_dated_run_needs_a_verify_column(self):
        problems = service.check_spec(spec(verify=""))
        self.assertTrue(any("Verify" in p for p in problems))


class PlainWords(unittest.TestCase):
    """Messages that reach a person never tell them to type a command-line flag."""

    def test_engine_wording_becomes_the_windows_words(self):
        bad_code = ("The search returned nothing for 'ZZ999UM00' (typed twice). Check the code with:  "
                    "python gmes_open_screen.py --find ZZ999UM00")
        self.assertIn("Use Find on the 'Record a screen' page", service.plain(bad_code))
        typed = "fromDt was typed with --set, so the result was NOT checked against it " \
                "(--verify only runs with --from/--to)"
        out = service.plain(typed)
        self.assertNotIn("--", out)
        self.assertIn("was typed into the screen", out)
        self.assertIn("NOT checked", out)                    # the meaning is kept
        self.assertNotIn("--", service.plain("a date-constrained run requires --verify COLUMN[=VALUE]"))
        self.assertEqual(service.plain("nothing special"), "nothing special")

    def test_every_record_check_detail_is_plain(self):
        rec = good_rec(verified=None, warnings=["something --grid something"])
        for c in service.judge(spec(date_from="", date_to="", verify=""), rec, good_rec(),
                               gmes_batch.PlanItem(code="P1112UM00")):
            self.assertNotIn("--", c["detail"], c)


class TheFiveQuestions(unittest.TestCase):
    def desc(self, **kw):
        d = {"grids": [{"name": "grdMain", "suggested": True}], "rivals": False,
             "date_fields": ["planYmd"], "looks_monthly": False,
             "trees": [{"names": ["SEEG-P", "VD", "MAIN Part"]}],
             "verify_candidates": ["planYmd"], "has_inquiry": True}
        d.update(kw)
        return {q: (a, t) for q, a, t in service.five_questions(d)}

    def test_a_plain_screen_is_all_ok(self):
        self.assertTrue(all(t == "ok" for _a, t in self.desc().values()))

    def test_no_vd_is_a_decision_never_a_substitute(self):
        a, t = self.desc(trees=[{"names": ["SEEG-P"]}])["Is there a division, and which?"]
        self.assertEqual(t, "decide")
        self.assertIn("never substitute", a)

    def test_rival_grids_and_a_month_and_a_live_monitor(self):
        q = self.desc(rivals=True, grids=[{"name": "a", "suggested": True}, {"name": "b", "suggested": False}])
        self.assertEqual(q["Which grid is the report?"][1], "decide")
        self.assertIn("MONTH", self.desc(looks_monthly=True)["Is the period a date or a month?"][0])
        live = self.desc(date_fields=[], has_inquiry=False)
        self.assertEqual(live["Is it a live monitor?"][1], "warn")

    def test_no_date_column_to_verify_is_said(self):
        self.assertEqual(self.desc(verify_candidates=[])["How can the date be verified?"][1], "warn")


class TheRecordCheck(unittest.TestCase):
    def plan_ok(self):
        return gmes_batch.PlanItem(code="P1112UM00")

    def test_a_clean_recording_passes(self):
        checks = service.judge(spec(), good_rec(), good_rec(), self.plan_ok())
        self.assertEqual(service.verdict(checks), "PASSED", checks)

    def test_a_failed_run(self):
        checks = service.judge(spec(), {"ok": False, "error": "no rows"})
        self.assertEqual(service.verdict(checks), "FAILED")

    def test_the_wrong_screen_fails(self):
        checks = service.judge(spec(), good_rec(screen="P1111UM00"), good_rec(), self.plan_ok())
        self.assertEqual(service.verdict(checks), "FAILED")

    def test_an_unconfirmed_division_fails(self):
        self.assertEqual(service.verdict(service.judge(spec(), good_rec(division=""), good_rec(),
                                                       self.plan_ok())), "FAILED")

    def test_an_empty_file_fails(self):
        rec = good_rec(files=files(1, size=10))
        self.assertEqual(service.verdict(service.judge(spec(), rec, good_rec(), self.plan_ok())), "FAILED")

    def test_csv_rows_that_differ_warn(self):
        checks = service.judge(spec(), good_rec(csv_rows=60), good_rec(), self.plan_ok())
        self.assertEqual(service.verdict(checks), "PASSED WITH WARNINGS")

    def test_an_unverified_dated_run_fails_and_a_typed_period_warns(self):
        self.assertEqual(service.verdict(service.judge(spec(), good_rec(verified=None), good_rec(),
                                                       self.plan_ok())), "FAILED")
        typed = good_rec(verified=None, warnings=["fromDt was typed with --set, so the result was NOT checked"])
        s = spec(date_from="", date_to="", verify="", sets={"fromDt": "202609"})
        typed["applied"] = {"fromDt": "202609"}
        self.assertEqual(service.verdict(service.judge(s, typed, good_rec(), self.plan_ok())),
                         "PASSED WITH WARNINGS")

    # -- HISTORY.md Phase 122 ------------------------------------------------------
    def test_an_empty_answer_on_a_proven_grid_passes(self):
        empty = good_rec(rows=0, files=[], verified=None, empty=True, csv_rows=None,
                         notes=["G-MES has no rows for 20261005: an empty answer, so no file was written"])
        checks = service.judge(spec(), empty, None, self.plan_ok())
        self.assertNotIn("fail", [c["status"] for c in checks], checks)
        self.assertNotIn("warn", [c["status"] for c in checks], checks)

    def test_a_summary_without_a_date_column_is_proven_by_the_read_back(self):
        s = spec(date_from="", date_to="", verify="", sets={"startDay": "20261005", "endDay": "20261005"})
        rec = good_rec(verified=None, applied={"startDay": "20261005", "endDay": "20261005"},
                       notes=["startDay: typed into the screen and read back right before Inquiry - "
                              "the result has no date column to check it in"])
        checks = service.judge(s, rec, good_rec(), self.plan_ok(), {"spread": None})
        self.assertEqual(service.verdict(checks), "PASSED", checks)

    def test_a_screen_that_defines_its_own_period_shows_the_spread_and_passes(self):
        s = spec(date_from="", date_to="", verify="", sets={"fromDt": "202610", "toDt": "202610"})
        rec = good_rec(verified=None, applied={"fromDt": "202610", "toDt": "202610"},
                       notes=["fromDt: typed into the screen and read back right before Inquiry - "
                              "this screen defines its own period (recorded decision)"])
        spread = {"column": "planYmd", "rows": 441, "dated": 441, "inside": 278,
                  "outside": {"20260928": 100, "20260929": 63}}
        checks = service.judge(s, rec, good_rec(), self.plan_ok(), {"spread": spread})
        self.assertEqual(service.verdict(checks), "PASSED", checks)
        detail = next(c["detail"] for c in checks if c["name"] == "The rows carry the requested period")
        self.assertIn("278 of 441", detail)
        self.assertIn("2026-09-28", detail)

    def test_a_filter_that_did_not_take_fails(self):
        s = spec(sets={"Model": "UA65"})
        self.assertEqual(service.verdict(service.judge(s, good_rec(), good_rec(), self.plan_ok())), "FAILED")
        ok = good_rec(applied={"Model": "UA65"})
        self.assertEqual(service.verdict(service.judge(s, ok, good_rec(), self.plan_ok())), "PASSED")

    def test_not_remembered_fails(self):
        self.assertEqual(service.verdict(service.judge(spec(), good_rec(profile=None), good_rec(),
                                                       self.plan_ok())), "FAILED")

    def test_a_replay_that_fails_or_differs(self):
        self.assertEqual(service.verdict(service.judge(spec(), good_rec(), {"ok": False, "error": "x"},
                                                       self.plan_ok())), "FAILED")
        self.assertEqual(service.verdict(service.judge(spec(), good_rec(), good_rec(rows=63),
                                                       self.plan_ok())), "PASSED WITH WARNINGS")

    def test_not_ready_for_batches_fails(self):
        blocked = gmes_batch.PlanItem(code="P1112UM00", blocked="no verify column")
        self.assertEqual(service.verdict(service.judge(spec(), good_rec(), good_rec(), blocked)), "FAILED")

    def test_every_warning_is_listed(self):
        checks = service.judge(spec(), good_rec(warnings=["24 of 66 rows are shown"]), good_rec(),
                               self.plan_ok())
        self.assertTrue(any("24 of 66" in c["detail"] for c in checks))


class ATypedMonth(unittest.TestCase):
    """Q321KUM00: the month is typed (fromDt=toDt=202609). What can be proven - the screen
    holds it, the rows' own dates - and the person's confirmation tied to a pattern."""

    def setUp(self):
        path = os.path.join(DATA, service.CONFIRM_FILE)
        if os.path.exists(path):
            os.remove(path)
        self.spec = spec(code="Q321KUM00", division="MAIN Part", date_from="", date_to="", verify="",
                         sets={"fromDt": "202609", "toDt": "202609"})
        self.rec = good_rec(screen="Q321KUM00", division="MAIN Part", verified=None, csv_rows=None,
                            applied={"fromDt": "202609", "toDt": "202609"},
                            warnings=["fromDt was typed with --set, so the result was NOT checked"])

    def rows(self, dates):
        return [{"planYmd": d, "fstRegDt": "20260930101010"} for d in dates]

    def test_the_month_and_its_edges(self):
        self.assertEqual(service.typed_period(self.spec), ("20260901", "20260930", "2026-09"))
        feb = spec(date_from="", date_to="", verify="", sets={"fromYm": "202602", "toYm": "202602"})
        self.assertEqual(service.typed_period(feb)[1], "20260228")
        dec = spec(date_from="", date_to="", verify="", sets={"fromYm": "202612", "toYm": "202612"})
        self.assertEqual(service.typed_period(dec)[1], "20261231")
        self.assertIsNone(service.typed_period(spec()))                 # a dated run is not typed

    def test_the_column_is_chosen_by_rule_never_by_how_friendly_it_is(self):
        period = service.typed_period(self.spec)
        rows = self.rows(["20260831"] * 7 + ["20260915"] * 93)
        # fstRegDt is ALL inside the month; planYmd is what the period means - planYmd
        # comes first in the dataset, so it is the one counted.
        s = service.date_spread(rows, ["planYmd", "fstRegDt"], period)
        self.assertEqual((s["column"], s["inside"], s["outside"]), ("planYmd", 93, {"20260831": 7}))
        self.assertEqual(service.outside_pattern(s, period), {"before": [1], "after": []})
        # named by the person -> that one, whatever it shows
        self.assertEqual(service.date_spread(rows, ["planYmd", "fstRegDt"], period, prefer="fstRegDt")["column"],
                         "fstRegDt")
        # a date-named column with no dates in it is passed over
        empty = [{"planYmd": "", "fstRegDt": "20260930101010"}]
        self.assertEqual(service.date_spread(empty, ["planYmd", "fstRegDt"], period)["column"], "fstRegDt")

    def test_all_rows_inside_is_green(self):
        period = service.typed_period(self.spec)
        s = service.date_spread(self.rows(["20260915"] * 5), ["planYmd"], period)
        checks = service.judge(self.spec, self.rec, self.rec, gmes_batch.PlanItem(code="Q321KUM00"),
                               {"spread": s})
        self.assertEqual(service.verdict(checks), "PASSED", checks)

    def test_rows_outside_warn_until_confirmed_then_green_next_month_too(self):
        period = service.typed_period(self.spec)
        s = service.date_spread(self.rows(["20260831"] * 7 + ["20260915"] * 93), ["planYmd"], period)
        result = {"kind": "recheck", "spec": self.spec, "rec": self.rec, "rep": None,
                  "plan": gmes_batch.PlanItem(code="Q321KUM00"), "evidence": {"spread": s}}
        first = service.finish(result)
        self.assertEqual(first["verdict"], "PASSED WITH WARNINGS")
        self.assertTrue(any(c.get("confirmable") for c in first["checks"]))
        after = service.confirm_and_rejudge(result, by="tester")
        self.assertEqual(after["verdict"], "PASSED", after["checks"])
        # October: the day before the period start again -> still covered
        oct_spec = dict(self.spec, sets={"fromDt": "202610", "toDt": "202610"})
        oct_rec = dict(self.rec, applied={"fromDt": "202610", "toDt": "202610"})
        oct_period = service.typed_period(oct_spec)
        oct_s = service.date_spread(self.rows(["20260930"] * 3 + ["20261005"] * 50), ["planYmd"], oct_period)
        conf = service.confirmations()["Q321KUM00"]
        checks = service.judge(oct_spec, oct_rec, None, None, {"spread": oct_s, "confirmation": conf})
        self.assertEqual(service.verdict(checks), "PASSED", checks)
        # a NEW pattern (rows from two weeks earlier) is not covered
        odd = service.date_spread(self.rows(["20260915"] * 3 + ["20261005"] * 50), ["planYmd"], oct_period)
        checks = service.judge(oct_spec, oct_rec, None, None, {"spread": odd, "confirmation": conf})
        self.assertEqual(service.verdict(checks), "PASSED WITH WARNINGS")
        self.assertTrue(any("NEW pattern" in c["detail"] for c in checks))

    def test_a_period_the_screen_did_not_hold_fails(self):
        rec = dict(self.rec, applied={"fromDt": "202608", "toDt": "202609"})
        checks = service.judge(self.spec, rec, None, None, {"spread": None})
        self.assertEqual(service.verdict(checks), "FAILED")

    def test_unreadable_dates_warn_and_cannot_be_confirmed(self):
        result = {"kind": "recheck", "spec": self.spec, "rec": self.rec, "rep": None, "plan": None,
                  "evidence": {"spread": None}}
        self.assertEqual(service.finish(result)["verdict"], "PASSED WITH WARNINGS")
        with self.assertRaises(service.Problem):
            service.confirm_and_rejudge(result)

    def test_record_and_check_reads_the_spread(self):
        period_seen = []

        def spread_fn(ws, code, rec, period, prefer=None):     # noqa: ARG001
            period_seen.append(period)
            return {"column": "planYmd", "rows": 5, "dated": 5, "inside": 5, "outside": {}}
        out = service.record_and_check(None, self.spec, log=lambda m: None,
                                       record_fn=lambda ws, s, log=None: self.rec,
                                       replay_fn=lambda ws, c, log=None: self.rec,
                                       plan_fn=lambda codes, p: [gmes_batch.PlanItem(code=codes[0])],
                                       spread_fn=spread_fn)
        self.assertEqual(period_seen, [("20260901", "20260930", "2026-09")])
        self.assertEqual(out["verdict"], "PASSED", out["checks"])


class RecordAndCheckFlow(unittest.TestCase):
    def test_record_then_bare_replay_then_plan_then_certificate(self):
        calls = []

        def rec_fn(ws, s, log=None):
            calls.append("record")
            return good_rec()

        def rep_fn(ws, code, log=None):
            calls.append(("replay", code))
            return good_rec()

        def plan_fn(codes, policy):
            calls.append(("plan", policy))
            return [gmes_batch.PlanItem(code=codes[0])]
        out = service.record_and_check(None, spec(), log=lambda m: None, record_fn=rec_fn,
                                       replay_fn=rep_fn, plan_fn=plan_fn)
        self.assertEqual(calls, ["record", ("replay", "P1112UM00"), ("plan", "yesterday")])
        self.assertEqual(out["verdict"], "PASSED")
        with open(out["certificate"], encoding="utf-8") as fh:
            cert = json.load(fh)
        self.assertEqual((cert["screen"], cert["verdict"]), ("P1112UM00", "PASSED"))
        self.assertEqual(service.certificates()["P1112UM00"]["verdict"], "PASSED")

    def test_a_failed_recording_is_not_replayed(self):
        replayed = []
        out = service.record_and_check(
            None, spec(), log=lambda m: None,
            record_fn=lambda ws, s, log=None: (_ for _ in ()).throw(RuntimeError("the query returned no rows")),
            replay_fn=lambda *a, **k: replayed.append(1))
        self.assertEqual((out["verdict"], replayed), ("FAILED", []))
        self.assertIn("no rows", out["checks"][0]["detail"])

    def test_stop_is_not_swallowed(self):
        def stopped(*a, **k):
            raise service.Stopped()
        with self.assertRaises(service.Stopped):
            service.record_and_check(None, spec(), record_fn=stopped)

    def test_a_bad_spec_runs_nothing(self):
        ran = []
        with self.assertRaises(service.Problem):
            service.record_and_check(None, spec(code="nope"), record_fn=lambda *a, **k: ran.append(1))
        self.assertEqual(ran, [])

    def test_stoppable_log_raises_at_the_next_step(self):
        stop = threading.Event()
        seen = []
        log = service.stoppable(seen.append, stop)
        log("one")
        stop.set()
        with self.assertRaises(service.Stopped):
            log("two")
        self.assertEqual(seen, ["one"])


class TheLibrary(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def write(self, folder, code, learned):
        with open(os.path.join(folder, f"{code}.json"), "w", encoding="utf-8") as fh:
            json.dump({"screen": code, "title": "T", "learned": learned, "values": {}}, fh)

    def test_import_takes_new_and_newer_and_keeps_newer_here(self):
        self.write(self.folder, "ZZ001UM00", "2026-09-30 10:00:00")
        self.write(self.folder, "notacode", "x")
        done, skipped = service.import_recordings(self.folder)
        self.assertEqual(done, ["ZZ001UM00"])
        self.write(self.folder, "ZZ001UM00", "2026-09-01 10:00:00")         # older
        done, skipped = service.import_recordings(self.folder)
        self.assertEqual(done, [])
        self.assertTrue(any("same or newer" in s for s in skipped))
        self.assertTrue(any(c["code"] == "ZZ001UM00" and c["recorded"] for c in service.library()))
        service.forget("ZZ001UM00")
        self.assertFalse(any(c["code"] == "ZZ001UM00" for c in service.library()))

    def test_a_renamed_recording_is_not_imported_under_the_wrong_code(self):
        with open(os.path.join(self.folder, "ZZ002UM00.json"), "w", encoding="utf-8") as fh:
            json.dump({"screen": "ZZ003UM00", "learned": "2026-10-06 10:00:00", "values": {}}, fh)
        done, skipped = service.import_recordings(self.folder)
        self.assertEqual(done, [])
        self.assertTrue(any("recording of ZZ003UM00" in s for s in skipped))


class Schedules(unittest.TestCase):
    def test_the_launcher_runs_this_app_and_waits_for_it(self):
        text = service.launcher_text("morning", command=[r"C:\Apps\GMES 100%\GMES_Automation.exe"])
        self.assertIn('start "" /wait', text)
        self.assertIn("--batch morning --unattended", text)
        self.assertIn("100%%", text)                        # a lone % would be dropped by cmd
        self.assertIn("if %code%==3 goto retry", text)
        self.assertIn("if %code%==4 goto retry", text)
        self.assertIn('cd /d "%~dp0.."', text)
        with self.assertRaises(ValueError):
            service.launcher_text("bad name!")

    def test_a_schedule_needs_a_saved_batch(self):
        # Task Scheduler is replaced even here: when this guard was broken on purpose
        # (a mutation check) the test registered a REAL task on the PC (HISTORY.md 117).
        with mock.patch.object(gmes_schedule, "_run_powershell", return_value=(0, "", "")) as ps:
            with self.assertRaises(service.Problem):
                service.schedule_create("nosuchbatch", gmes_schedule.parse_when("06:30", daily=True))
        ps.assert_not_called()

    def test_a_schedule_registers_the_apps_own_task(self):
        gmes_batch.save_batch("zz_test", ["P1112UM00"], "yesterday", "xlsx")
        self.addCleanup(gmes_batch.delete_batch, "zz_test")
        seen = {}

        def fake_ps(script, timeout=90):
            seen["script"] = script
            return 0, "", ""
        with mock.patch.object(gmes_schedule, "_run_powershell", side_effect=fake_ps):
            name = service.schedule_create("zz_test", gmes_schedule.parse_when("06:30", daily=True))
        self.assertEqual(name, "GMES_App_zz_test")
        self.assertIn("'GMES_App_zz_test'", seen["script"])
        with open(gmes_schedule.launcher_path("zz_test"), encoding="utf-8") as fh:
            self.assertIn("--batch zz_test", fh.read())


class SchedulesSayWhatTheyDo(unittest.TestCase):
    """HISTORY.md Phase 122: the list said 'Weekly' and nothing else; a schedule could
    export the same fixed day forever; a deleted batch left a schedule that failed."""

    def setUp(self):
        gmes_batch.save_batch("zz_sched", ["P1112UM00", "Q2251UM00"], "20260929", "xlsx")
        self.addCleanup(gmes_batch.delete_batch, "zz_sched")

    def tasks(self, *names):
        return [{"batch": n, "task": f"GMES_App_{n}", "state": "Ready", "next_run": "", "last_run": "",
                 "last_ok": None, "trigger": "Daily", "when": "every day at 06:30"} for n in names]

    def test_each_schedule_carries_what_it_runs_and_illogical_rules_are_named(self):
        with mock.patch.object(gmes_schedule, "list_tasks", return_value=self.tasks("zz_sched", "zz_gone")):
            rows = {t["batch"]: t for t in service.schedule_list()}
        self.assertEqual(rows["zz_sched"]["screens"], ["P1112UM00", "Q2251UM00"])
        self.assertIn("the fixed date 20260929", rows["zz_sched"]["dates"])
        self.assertTrue(any("on every run" in n for n in rows["zz_sched"]["notes"]))
        self.assertTrue(any("batch was deleted" in n for n in rows["zz_gone"]["notes"]))

    def test_the_schedule_decides_which_days_data_it_exports(self):
        with mock.patch.object(gmes_schedule, "_run_powershell", return_value=(0, "", "")):
            service.schedule_create("zz_sched", gmes_schedule.parse_when("06:30", daily=True), "yesterday")
        self.addCleanup(lambda: [os.path.exists(p) and os.unlink(p) for p in
                                 (gmes_schedule.launcher_path("zz_sched"), gmes_schedule.wrapper_path("zz_sched"))])
        b = service.batches()["zz_sched"]
        self.assertEqual((b["date"], b["screens"]), ("yesterday", ["P1112UM00", "Q2251UM00"]))
        self.assertFalse(service.fixed_dates("yesterday"))
        self.assertTrue(service.fixed_dates("keep"))
        self.assertTrue(service.fixed_dates("20261005"))


class TheSession(unittest.TestCase):
    def test_a_lock_held_past_the_wait_is_a_plain_problem(self):
        s = service.Session(log=lambda m: None)
        with mock.patch.object(gmes_core, "wait_for_run_lock", side_effect=gmes_core.RunLocked("busy")):
            with self.assertRaises(service.Problem):
                s.ensure()

    def test_a_held_lock_is_waited_for_and_stop_ends_the_wait(self):
        # Phase 128: Run pressed a second before a scheduled batch let go
        import tempfile
        import threading
        stop = threading.Event()
        said = []
        s = service.Session(log=said.append)
        lock = os.path.join(tempfile.mkdtemp(prefix="gmes-app-lock-"), ".run.lock")
        with mock.patch.object(gmes_core, "run_lock_path", lambda: lock):   # never the real profile
            other = gmes_core.acquire_run_lock()
            try:
                with mock.patch.object(gmes_core.time, "sleep", side_effect=lambda _s: stop.set()):
                    with self.assertRaises(service.Stopped):
                        s.ensure(stop_event=stop)
            finally:
                gmes_core.release_run_lock(other)
        self.assertIsNone(s.lock)
        self.assertTrue(any("Waiting for it to finish" in m and "Stop cancels." in m for m in said))

    def test_a_failed_sign_in_releases_the_lock(self):
        s = service.Session(log=lambda m: None)
        released = []
        with mock.patch.object(gmes_core, "acquire_run_lock", return_value="TOKEN"), \
                mock.patch.object(gmes_core, "release_run_lock", side_effect=released.append), \
                mock.patch.object(service.gmes_browsers, "recorded_profile_dir", return_value="x"), \
                mock.patch.object(gmes_core, "sign_in", return_value=False):
            with self.assertRaises(service.Problem):
                s.ensure()
        self.assertEqual(released, ["TOKEN"])
        self.assertIsNone(s.lock)

    def test_a_live_connection_is_reused(self):
        s = service.Session(log=lambda m: None)
        s.ws = object()
        with mock.patch.object(service.cdp_common, "evaluate", return_value=2), \
                mock.patch.object(gmes_core, "acquire_run_lock", return_value="TOKEN"), \
                mock.patch.object(gmes_core, "sign_in") as sign_in:
            self.assertIs(s.ensure(), s.ws)
        sign_in.assert_not_called()

    def test_the_lock_is_held_only_while_a_task_runs(self):
        # Phase 122: the window held the run lock from its first task until it was
        # closed, so every schedule that fired meanwhile found the browser "held".
        s = service.Session(log=lambda m: None)
        s.ws = object()
        released = []
        with mock.patch.object(service.cdp_common, "evaluate", return_value=2), \
                mock.patch.object(gmes_core, "acquire_run_lock", return_value="TOKEN") as take, \
                mock.patch.object(gmes_core, "release_run_lock", side_effect=released.append):
            s.ensure()
            self.assertEqual(s.lock, "TOKEN")
            s.release_lock()
            self.assertEqual((s.lock, released), (None, ["TOKEN"]))
            self.assertIsNotNone(s.ws)                         # the browser connection stays
            s.ensure()                                         # the next task takes it again
            self.assertEqual(take.call_count, 2)
        import web_server
        src = inspect.getsource(web_server.Hub.start)
        self.assertIn("self.session.release_lock()", src)


class Batches(unittest.TestCase):
    def setUp(self):
        self.prof = os.path.join(gmes_profile.SCREENS_DIR, "ZZ002UM00.json")
        with open(self.prof, "w", encoding="utf-8") as fh:
            json.dump({"screen": "ZZ002UM00", "title": "Test", "learned": "2026-09-30 10:00:00",
                       "values": {"division": "VD", "from": "20260929", "to": "20260929",
                                  "verify": "planYmd", "sets": {}}}, fh)
        self.addCleanup(os.remove, self.prof)

    def test_run_plan_reports_each_screen_and_writes_a_report(self):
        the_plan = service.plan(["ZZ002UM00", "NOPE1UM00"], "yesterday")
        self.assertTrue(the_plan[0].ready)
        self.assertFalse(the_plan[1].ready)
        started, finished = [], []
        session = mock.Mock()
        session.ensure.return_value = object()

        def fake_run(ws, log=None, **spec):
            log("  inquiry  : 3 rows")
            return {"ok": True, "rows": 3, "files": [], "warnings": [], "title": "Test"}
        with mock.patch.object(gmes_core, "run_screen", side_effect=fake_run), \
                mock.patch.object(gmes_core, "check_pc_clock", return_value=(None, None)):
            out = service.run_plan(session, the_plan, "yesterday", log=lambda m: None,
                                   on_start=started.append,
                                   on_result=lambda c, o: finished.append((c, o["ok"])))
        self.assertEqual(started, ["ZZ002UM00"])
        self.assertEqual(finished, [("ZZ002UM00", True)])
        self.assertEqual(out["counts"]["ok"], 1)
        self.assertEqual(out["counts"]["blocked"], 1)
        self.assertTrue(out["report"] and os.path.isfile(out["report"]))

    def test_stop_ends_the_batch_with_a_report(self):
        the_plan = service.plan(["ZZ002UM00"], "yesterday")
        stop = threading.Event()
        session = mock.Mock()
        session.ensure.return_value = object()

        def fake_run(ws, log=None, **spec):
            stop.set()
            log("  next step")
            return {"ok": True}
        with mock.patch.object(gmes_core, "run_screen", side_effect=fake_run), \
                mock.patch.object(gmes_core, "check_pc_clock", return_value=(None, None)):
            out = service.run_plan(session, the_plan, "yesterday", log=lambda m: None, stop_event=stop)
        self.assertTrue(out["stopped"])
        self.assertEqual(out["results"][0]["status"], "failed")

    def test_save_and_list_batches(self):
        service.save_batch("zz_b", ["ZZ002UM00"], "today", "both")
        self.addCleanup(service.delete_batch, "zz_b")
        self.assertEqual(service.batches()["zz_b"]["date"], "today")
        with self.assertRaises(service.Problem):
            service.save_batch("bad name", ["ZZ002UM00"], "today")


class RowExportSharesTheSession(unittest.TestCase):
    def test_attach_uses_the_sessions_connection_and_close_leaves_it_open(self):
        import gmes_rowexport as rowexport
        r = rowexport.Runner(rowexport.Settings(), log=lambda m: None)
        ws = mock.Mock()
        with mock.patch.object(rowexport.cdp_common, "send"):
            r.attach(ws)
        r.close()
        ws.close.assert_not_called()
        self.assertIsNone(r.lock)


class TheWindow(unittest.TestCase):
    """The window is a page served from this PC (web_server.py). These tests run the
    real server on a free port, with the real handler, and talk to it over HTTP."""

    @classmethod
    def setUpClass(cls):
        import web_server
        cls.ws = web_server
        cls.hub = web_server.Hub(selftest=lambda: 0)
        cls.api = web_server.Api(cls.hub)
        cls.token = "test-token"
        port_ref = [0]
        cls.server = web_server.QuietServer(("127.0.0.1", 0), web_server.make_handler(cls.api, cls.token, port_ref))
        port_ref[0] = cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    @unittest.skipUnless(os.name == "nt", "the folder picker is Windows-only")
    def test_the_folder_picker_can_be_built(self):
        # HISTORY.md Phase 120: every Browse click failed with "incompatible types,
        # c_wchar_Array_260 instance instead of c_wchar_p instance" and opened nothing.
        import ctypes
        info, name = self.ws.browse_info("Save the files in")
        name.value = "folder"
        self.assertEqual(ctypes.wstring_at(info.pszDisplayName), "folder")
        self.assertEqual(info.lpszTitle, "Save the files in")

    def test_a_rerecord_starts_from_the_remembered_options(self):
        # Re-recording used to show every option unticked, so a re-record silently
        # dropped what the last recording had switched on (HISTORY.md Phase 120).
        js = read_text(os.path.join(self.ws.web_dir(), "app.js"))
        self.assertIn("(d.profile || {}).options", js)
        self.assertIn("checked: o.enabled && (kept.has(o.key) || kept.has(o.label))", js)

    # -- HISTORY.md Phase 121 ----------------------------------------------------

    def test_a_successful_summary_is_not_red(self):
        c = self.ws.classify
        self.assertEqual(c("  2 succeeded, 0 failed, 0 skipped, 0 not run  (of 2)"), "ok")
        self.assertEqual(c("  SCREEN         STATUS       ROWS  FILES / ERROR"), "muted")
        self.assertEqual(c("  SCREEN       STATUS      ROWS  DATES             DETAIL"), "muted")
        self.assertEqual(c("  warning  : the export succeeded but this screen could not be remembered"), "warn")
        self.assertEqual(c("  | note: G-MES itself filters the month"), "warn")
        self.assertEqual(c("                                  ! could not copy to S:\\x"), "warn")
        # real trouble stays red
        self.assertEqual(c("  1 succeeded, 1 failed, 0 skipped, 0 not run  (of 2)"), "err")
        self.assertEqual(c("PROBLEM: the Inquiry button was not found"), "err")
        self.assertEqual(c("Record check FAILED - certificate x.json"), "err")

    def test_the_month_period_reaches_the_engine_as_days(self):
        status, _t, body = self.call("/api/spec", {"code": "Q321KUM00", "period": "month",
                                                    "from": "202609", "to": "202609", "verify": "planYmd"})
        self.assertEqual(status, 200)
        got = json.loads(body)
        self.assertEqual((got["spec"]["date_from"], got["spec"]["date_to"]), ("20260901", "20260930"))
        self.assertEqual(got["problems"], [])

    def loaded_runner(self, **changes):
        import gmes_rowexport as rowexport
        s = rowexport.Settings(division="MAIN Part", period="202609")
        r = rowexport.Runner(s, log=lambda *_a: None)
        r.rows, r.period = [{"outInspLotStatusNm": "PASS"}], "202609"
        new = rowexport.Settings(**dict({"division": "MAIN Part", "period": "202609"}, **changes))
        return r, new

    def test_row_export_refuses_a_list_loaded_for_other_settings(self):
        # A failed reload, or a changed organization without a reload, used to export
        # the OLD rows under the new settings.
        r, same = self.loaded_runner(start_row=5, out_dir="x")      # not part of the list
        self.assertEqual(self.ws.list_changes(r, same), [])
        r, other = self.loaded_runner(division="LCM Part", extra_filters=["Model=UA65"])
        self.assertEqual(self.ws.list_changes(r, other), ["organization", "model"])
        r, other = self.loaded_runner(period="202608")
        self.assertEqual(self.ws.list_changes(r, other), ["period"])
        self.hub.runner = r
        try:
            with mock.patch.object(self.api, "_rowexport_settings", return_value=other):
                with self.assertRaises(service.Problem) as e:
                    self.api.task("rowexport_start", {})
            self.assertIn("Load the list", str(e.exception))
        finally:
            self.hub.runner = None

    def test_a_new_load_forgets_the_old_list_first(self):
        r, s = self.loaded_runner()
        self.hub.runner = r
        with mock.patch.object(self.api, "_rowexport_settings", return_value=s), \
                mock.patch.object(self.hub, "start", return_value="x"):
            self.api.task("rowexport_load", {})
        self.assertIsNone(self.hub.runner)

    def test_a_rerecord_keeps_the_filters_typed_into_the_screen(self):
        # Phase 122: R3220UM00 re-recorded from the window lost mskFromDate, mskToDate
        # and rdoSearchType=Line (no box for them) and then failed on its tree.
        js = read_text(os.path.join(self.ws.web_dir(), "app.js"))
        self.assertIn("Object.entries(last.sets || {}).filter(([k]) => !(k in filterInputs) && k !== typed.from", js)
        self.assertIn('more.value = rest.map(([k, v]) => `${k}=${v}`).join("; ")', js)

    def test_a_typed_period_keeps_its_verify_column(self):
        status, _t, body = self.call("/api/spec", {
            "code": "R3220UM00", "period": "none", "verify": "workYmd",
            "more": "mskFromDate=20261005; mskToDate=20261005; rdoSearchType=Line"})
        got = json.loads(body)["spec"]
        self.assertEqual(got["verify"], "workYmd")
        self.assertEqual(got["sets"]["rdoSearchType"], "Line")
        status, _t, body = self.call("/api/spec", {"code": "M4131UM00", "period": "none", "verify": "x"})
        self.assertIsNone(json.loads(body)["spec"]["verify"])     # nothing to check it against

    def test_unbound_period_boxes_are_found_and_filled_by_the_period_picker(self):
        # R3220UM00 (live describe): its Period boxes are unbound controls
        unbound = [{"label": "", "control": "rdoSearchType", "value": "Trend"},
                   {"label": "Period", "control": "mskFromDate", "value": "2026-10-06"},
                   {"label": "Period", "control": "mskToDate", "value": "2026-10-06"},
                   {"label": "", "control": "edt_mCombo", "value": "All"}]
        typed = service.typed_date_boxes(unbound)
        self.assertEqual((typed["from"], typed["to"], typed["width"]), ("mskFromDate", "mskToDate", 8))
        self.assertEqual(service.typed_date_boxes([{"label": "", "control": "edtX", "value": "All"}]), {})
        status, _t, body = self.call("/api/spec", {
            "code": "R3220UM00", "period": "day", "from": "20261005", "to": "20261005",
            "verify": "", "more": "rdoSearchType=Line", "typed_dates": typed})
        got = json.loads(body)["spec"]
        self.assertEqual(got["sets"], {"rdoSearchType": "Line", "mskFromDate": "20261005",
                                       "mskToDate": "20261005"})
        self.assertIsNone(got["date_from"])                       # nothing bound to write
        self.assertEqual(json.loads(body)["problems"], [])
        month = dict(typed, width=6)
        status, _t, body = self.call("/api/spec", {
            "code": "R3220UM00", "period": "month", "from": "202609", "to": "202609",
            "typed_dates": month})
        self.assertEqual(json.loads(body)["spec"]["sets"], {"mskFromDate": "202609", "mskToDate": "202609"})

    def test_the_console_can_never_squash_the_pages(self):
        # Phase 122.9: a 591px console saved on a big window took most of a smaller
        # one, and the pages painted their cards over it.
        css = read_text(os.path.join(self.ws.web_dir(), "app.css"))
        self.assertIn("grid-template-rows: minmax(0, 1fr) 8px clamp(90px, var(--act-h), 38%)", css)
        self.assertIn("#pages { min-height: 0; position: relative; overflow: hidden; }", css)
        self.assertRegex(css, r"\.page \{[^}]*overflow-y: auto")
        js = read_text(os.path.join(self.ws.web_dir(), "app.js"))
        self.assertIn("rect.height * 0.38", js)

    def test_the_activity_log_sits_at_the_right_and_cannot_squash_the_pages(self):
        # Phase 127: the owner's drawing - the log a full-height column on the right.
        # Capped at 45% of the width like the height cap above; a narrow window puts
        # it back under the pages, and the drag uses the same breakpoint.
        css = read_text(os.path.join(self.ws.web_dir(), "app.css"))
        self.assertIn("grid-template-columns: minmax(0, 1fr) 8px clamp(18rem, var(--act-w), 45%)", css)
        self.assertIn("@media (max-width: 1100px)", css)
        html = read_text(os.path.join(self.ws.web_dir(), "index.html"))
        self.assertLess(html.index('id="pages"'), html.index('id="activity"'))
        js = read_text(os.path.join(self.ws.web_dir(), "app.js"))
        self.assertIn("rect.width * 0.45", js)
        self.assertIn('matchMedia("(max-width: 1100px)")', js)
        self.assertIn('removeProperty("--act-w")', js)

    def test_enter_on_a_focused_button_presses_that_button(self):
        js = read_text(os.path.join(self.ws.web_dir(), "app.js"))
        self.assertIn('e.key === "Enter" && !(e.target instanceof HTMLButtonElement)', js)
        self.assertIn('running = b && !!S.task && S.task.name === "Row export"', js)

    def test_an_unknown_browser_choice_leaves_the_browser_alone(self):
        with mock.patch.object(self.hub.session, "close") as close:
            status, _t, _b = self.call("/api/browser", {"choice": "firefox"})
        self.assertEqual(status, 400)
        close.assert_not_called()

    def call(self, path, body=None, token=True, host=None):
        import urllib.error
        import urllib.request
        headers = {"X-Token": self.token} if token else {}
        if host:
            headers["Host"] = host
        data = None
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=30) as r:
                return r.status, r.headers.get("Content-Type", ""), r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Content-Type", ""), e.read()

    def wait_idle(self):
        for _ in range(200):
            if not self.hub.busy:
                return
            threading.Event().wait(0.05)
        self.fail("the task did not end")

    def test_the_page_and_its_script_are_served_with_the_right_types(self):
        """Windows' registry may call .js text/plain; with nosniff the browser then
        refuses to run it and the window stays empty (seen while building it)."""
        for path, ctype in (("/", "text/html"), ("/app.js", "text/javascript"), ("/app.css", "text/css")):
            status, got, body = self.call(path, token=False)
            self.assertEqual(status, 200, path)
            self.assertTrue(got.startswith(ctype), f"{path}: {got}")
            self.assertGreater(len(body), 500)
        self.assertEqual(self.call("/../web_server.py", token=False)[0], 404)
        self.assertEqual(self.call("/web_server.py", token=False)[0], 404)

    def test_the_screen_library_and_editor_through_the_window(self):
        # HISTORY.md Phase 131: the page's own calls, end to end, on a recording in the app's data
        import gmes_dossier
        code = "Q2241UM00"
        path = os.path.join(DATA, "screens", f"{code}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"screen": code, "title": "Process Defect Status", "learned": "2026-10-06 14:28:37",
                       "values": {"division": "BLOCK7", "sets": {"mskFromDate": "20261005"}, "verify": "deftCreYmd"},
                       "grid": {"name": "g", "dataset": "ds"}}, fh)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        self.addCleanup(lambda: shutil.rmtree(os.path.join(DATA, "screens", "library"), ignore_errors=True))
        with mock.patch.dict(os.environ, {"GMES_DOSSIER": ""}):
            status, _t, body = self.call("/api/dossiers")
            self.assertEqual(status, 200)
            self.assertIn(code, [r["code"] for r in json.loads(body)["screens"]])
            status, _t, body = self.call(f"/api/dossier?code={code}")
            d = json.loads(body)["dossier"]
            self.assertIn({"name": "Division", "value": "BLOCK7"}, d["recipe"])
            self.assertIn('"BLOCK7"', d["recording_text"])
            # preview writes nothing; save keeps a version; restore puts it back
            status, _t, body = self.call("/api/edit", {"code": code, "change": {"export": "csv"}, "dry_run": True})
            self.assertEqual(json.loads(body)["changes"], ["files: default -> csv"])
            self.assertNotIn("export", json.load(open(path, encoding="utf-8")))
            status, _t, body = self.call("/api/edit", {"code": code, "change": {"export": "csv"}})
            saved = json.loads(body)
            self.assertTrue(saved["saved"])
            self.assertEqual(json.load(open(path, encoding="utf-8"))["export"], "csv")
            status, _t, body = self.call(f"/api/version?code={code}&name={saved['version']}")
            self.assertEqual(json.loads(body)["changes"], ["Files: CSV (the grid as shown) -> xlsx (the default)"])
            status, _t, body = self.call("/api/restore", {"code": code, "name": saved["version"]})
            self.assertNotIn("export", json.load(open(path, encoding="utf-8")))
            # a refusal is a plain 400, not a crash
            status, _t, body = self.call("/api/edit", {"code": code, "change": {"export": "pdf"}})
            self.assertEqual(status, 400)
            self.assertIn("export is one of", json.loads(body)["error"])
            # notes
            status, _t, body = self.call("/api/note", {"code": code, "text": "the export menu is on GridStatus"})
            self.assertIn("GridStatus", json.loads(body)["notes"])
            # a screenshot: only with the window's token, only a screenshot name of that screen
            png = os.path.join(gmes_dossier.folder_for(code), gmes_dossier.SHOTS, "20261011_120000_result.png")
            os.makedirs(os.path.dirname(png), exist_ok=True)
            with open(png, "wb") as fh:
                fh.write(b"\x89PNG\r\n\x1a\nfake")
            ok = self.call(f"/shot?t={self.token}&code={code}&name=20261011_120000_result.png", token=False)
            self.assertEqual((ok[0], ok[1]), (200, "image/png"))
            self.assertEqual(self.call(f"/shot?t=wrong&code={code}&name=20261011_120000_result.png", token=False)[0], 403)
            self.assertEqual(self.call(f"/shot?t={self.token}&code={code}&name=..%5C{code}.json", token=False)[0], 404)
        index = self.call("/", token=False)[2].decode("utf-8")
        self.assertIn('data-page="library"', index)

    def test_popups_met_and_their_rules_through_the_window(self):
        # HISTORY.md Phase 132: the catalogue a run fills, read and ruled from the page
        import gmes_popups
        self.addCleanup(lambda: os.path.exists(gmes_popups.catalogue_path()) and os.remove(gmes_popups.catalogue_path()))
        with mock.patch.dict(os.environ, {"GMES_DOSSIER": ""}):
            gmes_popups.remember("S9502UP01", "popup", title="Notice", text="maintenance tonight", buttons=["Close"],
                                 action="closed")
            status, _t, body = self.call("/api/popups")
            self.assertEqual(status, 200)
            r = json.loads(body)
            self.assertIn("Sign-in", "Sign-in " + r["signin"])
            row = [p for p in r["popups"] if p["key"] == "S9502UP01"][0]
            self.assertEqual((row["rule"], row["effective"], row["count"]), ("auto", "auto", 1))
            status, _t, body = self.call("/api/popup_rule", {"key": "S9502UP01", "rule": "press:Close"})
            self.assertEqual(status, 200)
            self.assertEqual(gmes_popups.rule_for("S9502UP01"), "press:Close")
            # a rule that is not one, or a popup never met, is a plain 400
            self.assertEqual(self.call("/api/popup_rule", {"key": "S9502UP01", "rule": "click anything"})[0], 400)
            self.assertEqual(self.call("/api/popup_rule", {"key": "never-met", "rule": "stop"})[0], 400)

    def test_the_weekly_reports_guide_is_inside_the_app(self):
        # WEEKLY_REPORTS.md (HISTORY.md Phase 130): the manager's rules, the proofs, the pipeline - shipped with the
        # .exe and opened from the side panel. The text is escaped: a guide line can never become markup.
        status, got, body = self.call("/guide", token=False)
        self.assertEqual(status, 200)
        self.assertTrue(got.startswith("text/html"))
        page = body.decode("utf-8")
        self.assertIn("<h1>The MR.Park weekly reports", page)
        self.assertIn("Time Operation Rate(New)(%)", page)
        self.assertIn("&lt;= 75%", page)                                  # '<=' escaped, not a tag
        self.assertNotIn("<= 75%", page)
        self.assertEqual(self.call("/guide", host="evil.example")[0], 403)
        index = self.call("/", token=False)[2].decode("utf-8")
        self.assertIn('href="/guide"', index)
        self.assertIn('.nav-item[data-page]', self.call("/app.js", token=False)[2].decode("utf-8"))

    def test_only_this_apps_window_may_use_it(self):
        self.assertEqual(self.call("/api/state")[0], 200)
        self.assertEqual(self.call("/api/state", token=False)[0], 403)             # another web page
        self.assertEqual(self.call("/api/state", host="evil.example")[0], 403)     # DNS rebinding
        self.assertEqual(self.call("/api/nothing")[0], 404)
        self.assertEqual(self.call("/api/task/nothing", {})[0], 400)

    def test_every_call_the_page_makes_exists(self):
        with open(os.path.join(APP, "web", "app.js"), encoding="utf-8") as fh:
            script = fh.read()
        import re
        paths = set(re.findall(r'["`]/api/([a-z_\-/]+)', script))
        tasks = set(re.findall(r'runTask\("([a-z_]+)"', script))
        self.assertGreater(len(paths), 15)
        for p in paths:
            name = p.rstrip("/").replace("/", "_").replace("-", "_")
            if name == "task":
                continue
            self.assertTrue(hasattr(self.api, f"get_{name}") or hasattr(self.api, f"post_{name}"), p)
        with mock.patch.object(self.hub, "start", return_value="x") as start, \
                mock.patch.object(service, "plan", return_value=[gmes_batch.PlanItem(code="P1112UM00")]), \
                mock.patch.object(self.api, "_rowexport_settings", return_value=mock.Mock()), \
                mock.patch.object(self.ws, "list_changes", return_value=[]):
            for t in tasks:
                self.hub.runner = mock.Mock(rows=[{}])          # a load forgets it (Phase 121)
                body = {"code": "P1112UM00", "period": "none", "codes": ["P1112UM00"], "batch": "b",
                        "time": "06:30", "kind": "daily", "query": "plan"}
                with mock.patch("gmes_rowexport.select_rows", return_value=([0], 0)):
                    self.api.task(t, body)
            self.hub.runner = None
        self.assertGreaterEqual(start.call_count, len(tasks))

    def test_one_task_at_a_time_and_stop_ends_it_without_a_result(self):
        gate = threading.Event()

        def work(stop, log):
            gate.wait(5)
            if stop.is_set():
                raise service.Stopped()
            return {"never": True}
        first = self.hub.events[-1]["id"] if self.hub.events else 0
        tid = self.hub.start("long", work, needs_session=False)
        status, _t, body = self.call("/api/task/selftest", {})
        self.assertEqual(status, 409)                                  # the browser is one
        self.assertIn("long", json.loads(body)["error"])
        self.assertEqual(json.loads(self.call("/api/state")[2])["busy"], True)
        self.call("/api/stop", {})
        gate.set()
        self.wait_idle()
        ends = [e for e in self.hub.events if e["id"] > first and e["type"] == "task"
                and e.get("task_id") == tid and e["state"] != "start"]
        self.assertEqual([e["state"] for e in ends], ["stopped"])     # a stopped task never reports done

    def test_a_failed_task_says_why_in_plain_words(self):
        def work(stop, log):
            raise service.Problem("Pass --grid to be certain which one.")
        tid = self.hub.start("bad", work, needs_session=False)
        self.wait_idle()
        end = [e for e in self.hub.events if e.get("task_id") == tid and e["state"] == "failed"][0]
        self.assertNotIn("--", end["error"])

    def test_events_wait_for_news_and_a_new_server_is_noticed(self):
        after = self.hub.next_id - 1
        threading.Timer(0.3, lambda: self.hub.log("hello there", "ok")).start()
        got = self.hub.events_after(after, wait=5)
        self.assertEqual([e["text"] for e in got["events"] if e["type"] == "log"], ["hello there"])
        self.assertTrue(self.hub.events_after(self.hub.next_id + 50, wait=1)["reset"])

    def test_appearance_is_kept_and_cleaned(self):
        status, _t, _b = self.call("/api/settings", {"appearance": {"theme": "Neon", "size": 133}})
        self.assertEqual(status, 200)
        got = json.loads(self.call("/api/settings")[2])["appearance"]
        self.assertEqual((got["theme"], got["size"]), ("Light", 140))
        self.call("/api/settings", {"appearance": {}})

    def test_the_side_panel_choice_is_kept_and_cleaned(self):
        # full or icons only (HISTORY.md Phase 125); anything else becomes "full"
        self.call("/api/settings", {"nav": {"collapsed": 1, "evil": "<script>"}})
        self.assertEqual(json.loads(self.call("/api/settings")[2])["nav"], {"collapsed": True})
        self.call("/api/settings", {"nav": "garbage"})
        self.assertEqual(json.loads(self.call("/api/settings")[2])["nav"], {"collapsed": False})
        self.call("/api/settings", {"nav": {"collapsed": False}})

    def test_every_side_panel_item_names_itself_for_icons_only(self):
        import re
        with open(os.path.join(APP, "web", "index.html"), encoding="utf-8") as fh:
            page = fh.read()
        buttons = re.findall(r'<button class="nav-item"[^>]*>', page)
        self.assertEqual(len(buttons), 9)            # + Screen library (HISTORY.md Phase 131)
        for b in buttons:                          # a collapsed item is only an icon
            self.assertRegex(b, r'aria-label="[^"]+"')
        self.assertIn('id="nav-toggle"', page)
        self.assertIn('aria-controls="nav"', page)
        with open(os.path.join(APP, "web", "app.js"), encoding="utf-8") as fh:
            script = fh.read()
        self.assertIn("setupNav()", script)
        self.assertIn('e.key.toLowerCase() === "b"', script)

    def test_a_confirmation_needs_a_check(self):
        self.hub.last_check = None
        status, _t, body = self.call("/api/confirm", {})
        self.assertEqual(status, 400)
        self.assertIn("record check", json.loads(body)["error"])

    def test_plan_items_reach_the_page_with_their_state(self):
        item = gmes_batch.PlanItem(code="P1112UM00", blocked="not recorded")
        self.assertEqual(self.ws.plan_view([item])[0]["ready"], False)
        self.assertEqual(self.ws.jsonable({"x": item})["x"]["ready"], False)
        json.dumps(self.ws.jsonable({"a": {1, 2}, "b": object()}))         # never a TypeError

    def test_a_closed_window_mid_request_is_not_a_problem(self):
        logged = []
        with mock.patch("socketserver.BaseServer.handle_error", side_effect=lambda *a: logged.append(1)):
            try:
                raise ConnectionResetError(10054, "closed")
            except ConnectionResetError:
                self.server.handle_error(None, ("127.0.0.1", 1))
            try:
                raise ValueError("a real bug")
            except ValueError:
                self.server.handle_error(None, ("127.0.0.1", 1))
        self.assertEqual(logged, [1])                                    # only the real bug


class NoConsoleWindows(unittest.TestCase):
    """A windowed program's console children (PowerShell, tasklist, robocopy) each
    flashed a CMD window over the app; they now start without one."""

    def test_children_start_without_a_console_unless_they_choose(self):
        import subprocess
        app_env.hide_console_windows()
        base = subprocess.Popen.__mro__[1]
        with mock.patch.object(base, "__init__", return_value=None) as init:
            subprocess.Popen(["tasklist"])
            self.assertEqual(init.call_args.kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)
            subprocess.Popen(["x"], creationflags=subprocess.CREATE_NEW_CONSOLE)
            self.assertEqual(init.call_args.kwargs["creationflags"], subprocess.CREATE_NEW_CONSOLE)


def _contrast(a, b):
    def lum(h):
        r, g, b_ = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4   # noqa: E731
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b_)
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class Appearance(unittest.TestCase):
    """Themes, fonts and text size: every theme complete and readable, and a bad
    settings file never stops the window from opening."""

    def test_every_theme_has_every_colour(self):
        import themes
        need = set(themes.THEMES["Light"])
        for name, palette in themes.THEMES.items():
            self.assertEqual(set(palette) ^ need, set(), name)
            for key, value in palette.items():
                self.assertRegex(value, r"^#[0-9A-Fa-f]{6}$", f"{name}.{key}")

    def test_every_theme_is_readable(self):
        """WCAG AA (4.5:1) for text and for the text on every coloured button."""
        import themes
        pairs = (("text", "card", 7), ("text", "bg", 7), ("text", "field", 7), ("muted", "card", 4.5),
                 ("muted", "bg", 4.5), ("muted", "tile", 4.5), ("on_accent", "accent", 4.5),
                 ("#FFFFFF", "ok", 4.5), ("#FFFFFF", "err", 4.5), ("accent", "card", 4.5),
                 ("accent", "accent_soft", 4.5), ("ok_text", "ok_soft", 4.5),
                 ("warn_text", "warn_soft", 4.5), ("err_text", "err_soft", 4.5),
                 ("console_text", "console", 7), ("header_text", "header", 7))
        for name, p in themes.THEMES.items():
            for fg, bg, least in pairs:
                ratio = _contrast(p.get(fg, fg), p[bg])
                self.assertGreaterEqual(ratio, least, f"{name}: {fg} on {bg} = {ratio:.2f}")

    def test_every_colour_the_page_uses_is_a_theme_token(self):
        import re
        import themes
        with open(os.path.join(APP, "web", "app.css"), encoding="utf-8") as fh:
            css = fh.read()
        tokens = {k.replace("_", "-") for k in themes.THEMES["Light"]}
        own = {"font", "mono", "scale", "left", "act-h", "act-w", "radius"}
        for name in set(re.findall(r"var\(--([a-z0-9-]+)\)", css)):
            self.assertIn(name, tokens | own, name)

    def test_a_bad_or_foreign_settings_file_still_opens(self):
        import themes
        fonts = {"Segoe UI", "Consolas", "Calibri"}
        self.assertEqual(themes.resolve_appearance(None, fonts),
                         {"theme": "Light", "font": "Segoe UI", "mono": "Consolas", "size": 100})
        got = themes.resolve_appearance({"theme": "Neon", "font": "Comic Sans MS", "mono": ["x"],
                                         "size": "huge"}, fonts)
        self.assertEqual(got, {"theme": "Light", "font": "Segoe UI", "mono": "Consolas", "size": 100})
        self.assertEqual(themes.resolve_appearance({"size": 130}, fonts)["size"], 125)    # nearest offered
        self.assertEqual(themes.resolve_appearance({"size": 10}, fonts)["size"], 90)
        self.assertEqual(themes.resolve_appearance({"font": "Calibri"}, fonts)["font"], "Calibri")
        # A PC without Segoe UI (another Windows language pack): the first font it has.
        self.assertEqual(themes.resolve_appearance({}, {"Tahoma"})["font"], "Tahoma")
        self.assertEqual(themes.resolve_appearance({}, set())["font"], "system-ui")

    def test_installed_fonts_never_raise(self):
        import themes
        found = themes.installed_families()
        self.assertIsInstance(found, set)
        self.assertTrue(found <= set(themes.UI_FONTS + themes.MONO_FONTS))


class Settings(unittest.TestCase):
    def test_saving_merges_and_never_leaves_a_half_written_file(self):
        import app_settings
        app_settings.save(browser="edge")
        app_settings.save(appearance={"theme": "Sand"})
        self.assertEqual(app_settings.load()["browser"], "edge")              # merged, not replaced
        self.assertFalse(os.path.exists(app_settings.settings_file() + ".tmp"))
        with mock.patch("json.dump", side_effect=OSError("disk full")):
            app_settings.save(browser="chrome")
        self.assertEqual(app_settings.load()["browser"], "edge")              # the old file survived
        app_settings.save(browser="auto", appearance={})

    def test_dividers_are_remembered_and_forgotten(self):
        import app_settings
        app_settings.set_pane("reports", 0.55)
        self.assertEqual(app_settings.pane("reports"), 0.55)
        app_settings.set_pane("reports", None)
        self.assertIsNone(app_settings.pane("reports"))




if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        shutil.rmtree(DATA, ignore_errors=True)
