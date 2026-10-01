"""Offline tests for GMES Automation (GMES/). No browser, no network, no G-MES.

    python GMES/tests/test_gmes_app.py

Everything runs against a temporary data folder (GMES_APP_DATA), so a test never
touches the person's recordings, logs or settings. They guard the DECISIONS - the
record check, plans, schedules, the session's refusals - not the browser half,
which is proven live (HISTORY.md).
"""
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
        self.assertEqual(service.check_spec(spec(date_from="202609", date_to="202609")), [])
        self.assertEqual(service.check_spec(spec(date_from="", date_to="", verify="")), [])

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


class TheSession(unittest.TestCase):
    def test_a_held_lock_is_a_plain_problem(self):
        s = service.Session(log=lambda m: None)
        with mock.patch.object(gmes_core, "acquire_run_lock", side_effect=gmes_core.RunLocked("busy")):
            with self.assertRaises(service.Problem):
                s.ensure()

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
                mock.patch.object(gmes_core, "sign_in") as sign_in:
            self.assertIs(s.ensure(), s.ws)
        sign_in.assert_not_called()


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
        import rowexport
        r = rowexport.Runner(rowexport.Settings(), log=lambda m: None)
        ws = mock.Mock()
        with mock.patch.object(rowexport.cdp_common, "send"):
            r.attach(ws)
        r.close()
        ws.close.assert_not_called()
        self.assertIsNone(r.lock)


class TheWindow(unittest.TestCase):
    def test_every_page_opens_and_every_message_has_a_handler(self):
        import gmes_app
        try:
            app = gmes_app.App()
        except Exception as e:                               # noqa: BLE001 - no display
            self.skipTest(f"no display: {e}")
        fallback = app.sink.fallback
        try:
            app.update()
            for key in app.pages:
                app.show(key)
                app.update()
            app.q.put(("nonsense", None))
            app.sink.write("Signed in as 'Test Person'.\n")
            app._pump()
            self.assertIn("Test Person", app.lbl_user.cget("text"))
            self.assertFalse(app.busy)
        finally:
            sys.stdout = sys.stderr = fallback or sys.__stdout__
            app.destroy()

    def test_one_task_at_a_time_and_stop(self):
        import gmes_app
        try:
            app = gmes_app.App()
        except Exception as e:                               # noqa: BLE001
            self.skipTest(f"no display: {e}")
        fallback = app.sink.fallback
        try:
            gate = threading.Event()
            results = []

            def work(stop, log):
                gate.wait(5)
                if stop.is_set():
                    raise service.Stopped()
                return 1
            with mock.patch.object(gmes_app.ui, "tell"):
                self.assertTrue(app.run_task("t", work, results.append, needs_session=False))
                self.assertFalse(app.run_task("t2", work, results.append, needs_session=False))
                app.stop()
                gate.set()
                app.worker.join(5)
                app._pump()
            self.assertFalse(app.busy)
            self.assertEqual(results, [])                    # a stopped task never reports done
        finally:
            sys.stdout = sys.stderr = fallback or sys.__stdout__
            app.destroy()

    def test_a_new_look_rebuilds_the_window_and_keeps_what_it_showed(self):
        import app_settings
        import gmes_app
        import ui_kit as ui
        try:
            app = gmes_app.App()
        except Exception as e:                               # noqa: BLE001
            self.skipTest(f"no display: {e}")
        fallback = app.sink.fallback
        try:
            app.update()
            app.log("a line before the rebuild", "ok")
            result = {"verdict": "PASSED", "certificate": "c.json", "spec": spec(), "checks": [
                {"status": "ok", "name": "The screen opens", "detail": "P1112UM00"}]}
            app.pages["record"]._recorded(result)
            app.pages["reports"].v_search.set("plan")
            app.show("appearance")
            self.assertTrue(app.apply_appearance(theme="Dark", size=125))
            app.update()
            self.assertEqual((ui.APPEARANCE["theme"], ui.APPEARANCE["size"]), ("Dark", 125))
            self.assertEqual(ui.C["bg"], ui.THEMES["Dark"]["bg"])
            self.assertEqual(app_settings.appearance()["theme"], "Dark")          # remembered
            self.assertEqual(app.current, "appearance")                          # same page
            self.assertIn("a line before the rebuild", app.log_text.get("1.0", "end"))
            self.assertIs(app.pages["record"].last_result, result)              # the check stays
            self.assertEqual(app.pages["reports"].v_search.get(), "plan")
            self.assertEqual(app.pages["record"].check_table.tree.get_children(), ("0",))
            app.busy, app.task_name = True, "something"
            with mock.patch.object(gmes_app.ui, "tell") as told:
                self.assertFalse(app.apply_appearance(theme="Light"))            # never mid-task
            told.assert_called_once()
            self.assertEqual(ui.APPEARANCE["theme"], "Dark")
            app.busy = False
            self.assertTrue(app.apply_appearance(**ui.APPEARANCE_DEFAULTS))
        finally:
            sys.stdout = sys.stderr = fallback or sys.__stdout__
            app.destroy()
            app_settings.save(appearance={}, panes={})


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
        import ui_kit as ui
        need = set(ui.THEMES["Light"])
        for name, palette in ui.THEMES.items():
            self.assertEqual(set(palette) ^ need, set(), name)
            for key, value in palette.items():
                self.assertRegex(value, r"^#[0-9A-Fa-f]{6}$", f"{name}.{key}")

    def test_every_theme_is_readable(self):
        """WCAG AA (4.5:1) for text and for the text on every coloured button."""
        import ui_kit as ui
        pairs = (("text", "card", 7), ("text", "bg", 7), ("text", "field", 7), ("muted", "card", 4.5),
                 ("muted", "bg", 4.5), ("muted", "tile", 4.5), ("on_accent", "accent", 4.5),
                 ("#FFFFFF", "ok", 4.5), ("#FFFFFF", "err", 4.5), ("accent", "card", 4.5),
                 ("accent", "accent_soft", 4.5), ("ok_text", "ok_soft", 4.5),
                 ("warn_text", "warn_soft", 4.5), ("err_text", "err_soft", 4.5),
                 ("console_text", "console", 7), ("header_text", "header", 7))
        for name, p in ui.THEMES.items():
            for fg, bg, least in pairs:
                ratio = _contrast(p.get(fg, fg), p[bg])
                self.assertGreaterEqual(ratio, least, f"{name}: {fg} on {bg} = {ratio:.2f}")

    def test_a_bad_or_foreign_settings_file_still_opens(self):
        import ui_kit as ui
        fonts = {"Segoe UI", "Consolas", "Calibri"}
        self.assertEqual(ui.resolve_appearance(None, fonts),
                         {"theme": "Light", "font": "Segoe UI", "mono": "Consolas", "size": 100})
        got = ui.resolve_appearance({"theme": "Neon", "font": "Comic Sans MS", "mono": ["x"],
                                     "size": "huge"}, fonts)
        self.assertEqual(got, {"theme": "Light", "font": "Segoe UI", "mono": "Consolas", "size": 100})
        self.assertEqual(ui.resolve_appearance({"size": 130}, fonts)["size"], 125)    # nearest offered
        self.assertEqual(ui.resolve_appearance({"size": 10}, fonts)["size"], 90)
        self.assertEqual(ui.resolve_appearance({"font": "Calibri"}, fonts)["font"], "Calibri")
        # A PC without Segoe UI (another Windows language pack): the first font it has.
        self.assertEqual(ui.resolve_appearance({}, {"Tahoma"})["font"], "Tahoma")
        self.assertEqual(ui.resolve_appearance({}, set())["font"], "TkDefaultFont")

    def test_semibold_falls_back_to_bold(self):
        import ui_kit as ui
        self.assertEqual(ui.semibold("Segoe UI", 10, {"Segoe UI Semibold"}), ("Segoe UI Semibold", 10))
        self.assertEqual(ui.semibold("Bahnschrift", 10, {"Bahnschrift SemiBold"}), ("Bahnschrift SemiBold", 10))
        self.assertEqual(ui.semibold("Calibri", 10, set()), ("Calibri", 10, "bold"))


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


class Layout(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        import ui_kit as ui
        try:
            self.root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f"no display: {e}")
        self.root.geometry("1000x600")
        ui.setup_theme(self.root)
        self.addCleanup(self.root.destroy)

    def test_a_divider_keeps_its_share_when_the_window_changes(self):
        import tkinter as tk
        import ui_kit as ui
        store = {}
        with mock.patch.object(ui.Split, "store", (store.get, store.__setitem__)):
            split = ui.Split(self.root, "t", first=0.25)
            split.pack(fill="both", expand=True)
            split.add(tk.Frame(split), minsize=50)
            split.add(tk.Frame(split), minsize=50)
            self.root.update()
            self.assertAlmostEqual(split.sash_coord(0)[0] / split.winfo_width(), 0.25, delta=0.02)
            split.sash_place(0, 600, 1)                       # the person drags it
            split._dragged = True
            split._remember()
            self.assertAlmostEqual(store["t"], 600 / split.winfo_width(), places=3)
            self.root.geometry("1400x600")
            self.root.update()
            self.root.update()
            self.assertAlmostEqual(split.sash_coord(0)[0] / split.winfo_width(), store["t"], delta=0.02)
            split.reset()
            self.assertIsNone(store["t"])
            self.root.update()
            self.assertAlmostEqual(split.sash_coord(0)[0] / split.winfo_width(), 0.25, delta=0.02)
            # Next start: the remembered share is used.
            store["u"] = 0.7
            again = ui.Split(self.root, "u", first=0.3)
            self.assertEqual(again.fraction, 0.7)

    def test_text_follows_its_column_and_dead_labels_drop_out(self):
        import tkinter as tk
        import ui_kit as ui
        col = tk.Frame(self.root, width=500, height=100)
        col.pack(fill="x")
        col.pack_propagate(False)            # a laid-out column whose size the label cannot change:
        self.root.update()                   # no Configure comes, the fit must apply at once
        lbl = ui.note(col, "x " * 200, fit=True)
        lbl.pack(fill="x")
        self.root.update()
        first = int(lbl.cget("wraplength"))
        self.assertGreater(first, 900)                        # follows the 1000 px column, not 380
        for _ in range(20):                                   # a detail panel rebuilt many times
            ui.note(col, "y", fit=True).destroy()
        self.root.geometry("700x600")
        self.root.update()
        self.assertLess(int(lbl.cget("wraplength")), first)
        self.assertEqual(len(col._fit_labels), 1)             # no pile of bindings to dead labels


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        shutil.rmtree(DATA, ignore_errors=True)
