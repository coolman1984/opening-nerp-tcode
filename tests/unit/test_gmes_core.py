"""
Offline tests for the parts of gmes_core.py that do not need a browser.

There is no mock for G-MES (CLAUDE.md 4.3), so the browser-driven half is
verified against the live system by hand. What CAN be tested offline is every
decision the core makes about a screen it has already read: which control a
name refers to, which field is a date, which grid holds the results, how wide
a date to write. Those are exactly the decisions whose failures are silent -
a filter matched to the wrong control, an eight-digit code mistaken for a
date - so each case below is one of those failures.

    python tests/test_gmes_core.py
"""
import os
import sys
import unittest

# tests/unit/ is one level deeper than the original tests/, so this needs an
# extra dirname() to still reach the repo root and its flat gmes_*.py modules.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import gmes_core as core  # noqa: E402


def flt(column="", label="", control="edtThing", value="", visible=True,
        bound=True, dataset="dsFilterDVO", form="P1112WF00.xfdl.js"):
    return {"column": column, "label": label, "control": control, "value": value,
            "visible": visible, "bound": bound, "dataset": dataset, "form": form,
            "id": "win_0_1.form." + control, "kind": ""}


def grid(name, dataset, area, visible=True, form="P1112WM00.xfdl.js"):
    return {"name": name, "dataset": dataset, "area": area, "visible": visible,
            "form": form}


class Words(unittest.TestCase):
    def test_splits_camel_case(self):
        self.assertEqual(core.words("paramFromDate"), {"param", "from", "date"})

    def test_splits_underscores_and_digits(self):
        self.assertIn("checked", core.words("_checked"))

    def test_vendor_code_does_not_contain_the_word_end(self):
        # "paramVendorCode" contains the letters "end". A substring match
        # classified it as the period's end date.
        self.assertNotIn("end", core.words("paramVendorCode"))


class DateDetection(unittest.TestCase):
    def test_named_date_column_is_a_date(self):
        self.assertTrue(core.is_date_field(flt(column="paramFromDate")))

    def test_ymd_and_ym_are_dates(self):
        self.assertTrue(core.is_date_field(flt(column="planYmd")))
        self.assertTrue(core.is_date_field(flt(column="stdYm")))

    def test_masked_control_holding_eight_digits_is_a_date(self):
        self.assertTrue(core.is_date_field(
            flt(column="paramPeriod1", control="mskDateFrom", value="20260908")))

    def test_an_eight_digit_code_in_a_text_box_is_not_a_date(self):
        # A Production Order is 12 digits, a vendor code can be 8. Treating
        # the shape of the value as proof would silently overwrite one with
        # today's date.
        self.assertFalse(core.is_date_field(
            flt(column="paramVendorCode", control="edtVendor", value="10748321")))

    def test_a_label_naming_a_date_is_enough(self):
        self.assertTrue(core.is_date_field(
            flt(column="paramP1", control="mskP1", label="Plan Date")))


class DateTargets(unittest.TestCase):
    def test_finds_a_from_to_pair(self):
        info = {"filters": [flt(column="paramFromDate"), flt(column="paramEndDate"),
                            flt(column="paramPo", control="edtPo")]}
        frm, to, singles = core.date_targets(info)
        self.assertEqual(frm["column"], "paramFromDate")
        self.assertEqual(to["column"], "paramEndDate")
        self.assertEqual(singles, [])

    def test_a_screen_with_one_date_reports_it_as_a_single(self):
        # The old rule matched only *fromdate*/*enddate*, so this screen was
        # reported as having no date filter and ran on whatever was in it.
        info = {"filters": [flt(column="planYmd")]}
        frm, to, singles = core.date_targets(info)
        self.assertIsNone(frm)
        self.assertIsNone(to)
        self.assertEqual([s["column"] for s in singles], ["planYmd"])

    def test_a_vendor_code_is_never_the_end_date(self):
        info = {"filters": [flt(column="paramFromDate"),
                            flt(column="paramVendorCode", control="edtVendor",
                                value="10748321")]}
        frm, to, _ = core.date_targets(info)
        self.assertEqual(frm["column"], "paramFromDate")
        self.assertIsNone(to)


class DateWidth(unittest.TestCase):
    def test_full_date_into_an_empty_field(self):
        self.assertEqual(core.fit_date_to_field("20260908", ""), "20260908")

    def test_month_field_gets_six_digits(self):
        # Writing eight digits into a YYYYMM field is accepted and the query
        # then answers something else.
        self.assertEqual(core.fit_date_to_field("20260908", "202608"), "202609")

    def test_year_field_gets_four(self):
        self.assertEqual(core.fit_date_to_field("20260908", "2025"), "2026")

    def test_a_formatted_existing_value_still_counts_as_eight(self):
        self.assertEqual(core.fit_date_to_field("20260908", "2026-08-01"), "20260908")


class NormaliseDate(unittest.TestCase):
    def test_accepts_the_ways_people_type_it(self):
        for raw in ("20260907", "2026-09-07", "2026/09/07", " 2026.09.07 "):
            self.assertEqual(core.normalise_date(raw), "20260907")

    def test_blank_is_none_not_an_error(self):
        self.assertIsNone(core.normalise_date(""))
        self.assertIsNone(core.normalise_date(None))

    def test_rejects_a_date_that_does_not_exist(self):
        with self.assertRaises(ValueError):
            core.normalise_date("20260231")

    def test_rejects_a_partial_date_rather_than_guessing(self):
        with self.assertRaises(ValueError):
            core.normalise_date("2026-09")


class MatchFilter(unittest.TestCase):
    def setUp(self):
        self.info = {
            "filters": [flt(column="paramPo", label="Production Order", control="edtPo"),
                        flt(column="paramFromDate", label="Plan Date", control="mskDateFrom"),
                        flt(column="paramTecoYn", label="TECO", control="cboTeco")],
            "unbound": [flt(column="", label="Lot", control="edtLotNo", bound=False)],
        }

    def test_by_column(self):
        self.assertEqual(core.match_filter(self.info, "paramPo")["control"], "edtPo")

    def test_by_label_case_insensitively(self):
        self.assertEqual(core.match_filter(self.info, "production order")["column"],
                         "paramPo")

    def test_by_control_name(self):
        self.assertEqual(core.match_filter(self.info, "cboTeco")["column"], "paramTecoYn")

    def test_an_unbound_control_is_reachable_by_name(self):
        # A screen that binds none of its filters used to be undriveable.
        found = core.match_filter(self.info, "Lot")
        self.assertEqual(found["control"], "edtLotNo")
        self.assertFalse(found["bound"])

    def test_unknown_name_returns_none(self):
        self.assertIsNone(core.match_filter(self.info, "nothing like this"))

    def test_ambiguous_partial_returns_every_candidate(self):
        info = {"filters": [flt(column="paramFromDate", label="Plan Date"),
                            flt(column="paramEndDate", label="Plan Date To")]}
        found = core.match_filter(info, "date")
        self.assertIsInstance(found, list)
        self.assertEqual(len(found), 2)


class DateColumnNaming(unittest.TestCase):
    """A result column is only reported as a date when it is NAMED like one.
    Live output once listed prodTime (a time), planWeekno (a week number) and
    modelDesc (a model code) as "dates that came back", because all three are
    six or eight digits."""

    def named_like_a_date(self, column):
        return bool(core.words(column) & core._DATE_WORDS)

    def test_real_date_columns(self):
        for column in ("planYmd", "createDate", "workDt", "stdYm"):
            self.assertTrue(self.named_like_a_date(column), column)

    def test_look_alikes_are_not_dates(self):
        for column in ("prodTime", "planWeekno", "modelDesc", "poNo"):
            self.assertFalse(self.named_like_a_date(column), column)


class ChooseGrid(unittest.TestCase):
    def test_the_only_grid_wins(self):
        info = {"grids": [grid("grdMain", "dsMasterProdPlan", 400000)]}
        chosen, rivals = core.choose_grid(info)
        self.assertEqual(chosen["dataset"], "dsMasterProdPlan")
        self.assertEqual(rivals, [])

    def test_a_hidden_grid_is_not_chosen_over_a_visible_one(self):
        info = {"grids": [grid("grdHidden", "dsOther", 900000, visible=False),
                          grid("grdMain", "dsMain", 400000)]}
        chosen, _ = core.choose_grid(info)
        self.assertEqual(chosen["name"], "grdMain")

    def test_a_comparable_second_grid_is_reported_not_hidden(self):
        # Master-detail screens have two. Picking the larger silently is a
        # coin toss, and the wrong side of it exports the wrong data.
        info = {"grids": [grid("grdMaster", "dsMaster", 400000),
                          grid("grdDetail", "dsDetail", 380000)]}
        chosen, rivals = core.choose_grid(info)
        self.assertEqual(chosen["name"], "grdMaster")
        self.assertEqual([r["name"] for r in rivals], ["grdDetail"])

    def test_a_small_second_grid_is_not_an_ambiguity(self):
        info = {"grids": [grid("grdMaster", "dsMaster", 400000),
                          grid("grdTiny", "dsTiny", 9000)]}
        _, rivals = core.choose_grid(info)
        self.assertEqual(rivals, [])

    def test_prefer_by_dataset_name_settles_it(self):
        info = {"grids": [grid("grdMaster", "dsMaster", 400000),
                          grid("grdDetail", "dsDetail", 380000)]}
        chosen, rivals = core.choose_grid(info, prefer="dsDetail")
        self.assertEqual(chosen["name"], "grdDetail")
        self.assertEqual(rivals, [])

    def test_an_unmatched_preference_does_not_fall_back_silently(self):
        info = {"grids": [grid("grdMaster", "dsMaster", 400000)]}
        chosen, rivals = core.choose_grid(info, prefer="dsNoSuchThing")
        self.assertIsNone(chosen)
        self.assertTrue(rivals)

    def test_no_grids_at_all(self):
        self.assertEqual(core.choose_grid({"grids": []}), (None, []))


class Names(unittest.TestCase):
    def test_a_report_title_with_a_slash_becomes_a_usable_file_name(self):
        self.assertEqual(core.safe_name("Production Plan by Order(Line)"),
                         "Production Plan by Order(Line)")
        self.assertNotIn("/", core.safe_name("Plan / Actual"))
        self.assertNotIn(":", core.safe_name("Shift: A"))

    def test_an_empty_title_still_yields_a_name(self):
        self.assertEqual(core.safe_name("   "), "report")


class Digits(unittest.TestCase):
    def test_a_formatted_date_and_a_raw_one_compare_equal(self):
        self.assertEqual(core.digits_only("2026-09-08"), core.digits_only("20260908"))


class ScreenCodeShape(unittest.TestCase):
    """open_screen() reuses an already-open tab only for a full screen code or
    menu id. A partial one would match several open screens and pick whichever
    came first; a name has to go through the catalogue, which validates it."""

    PATTERN = r"[A-Za-z]{1,4}\d{4,}[A-Za-z0-9]*"

    def looks_like_a_code(self, text):
        import re
        return bool(re.fullmatch(self.PATTERN, text))

    def test_real_codes_are_recognised(self):
        for code in ("P1112UM00", "P1112WM00", "Q2241UM00", "PPM0219"):
            self.assertTrue(self.looks_like_a_code(code), code)

    def test_a_partial_code_is_not(self):
        self.assertFalse(self.looks_like_a_code("P111"))

    def test_a_screen_name_is_not(self):
        for name in ("Work Calendar", "production plan", "Master Prod. Plan"):
            self.assertFalse(self.looks_like_a_code(name), name)


class Profiles(unittest.TestCase):
    """What the tool remembers after a run that worked, and - more
    importantly - when it must refuse to trust that memory."""

    def setUp(self):
        import gmes_profile
        self.p = gmes_profile
        self.info = {
            "filters": [flt(column="paramFromDate", control="mskDateFrom"),
                        flt(column="paramEndDate", control="mskDateTo"),
                        flt(column="paramPo", control="edtPo")],
            "unbound": [],
            "grids": [grid("grdMain", "dsMasterProdPlan", 400000)],
        }

    def profile_for(self, info):
        return {"from": self.p.field_ref(info["filters"][0]),
                "to": self.p.field_ref(info["filters"][1]),
                "grid": self.p.grid_ref(info["grids"][0]),
                "fingerprint": self.p.fingerprint(info)}

    def test_an_unchanged_screen_has_no_problems(self):
        self.assertEqual(self.p.describe_change(self.profile_for(self.info),
                                                self.info), [])

    def test_the_same_screen_fingerprints_the_same_twice(self):
        self.assertEqual(self.p.fingerprint(self.info), self.p.fingerprint(self.info))

    def test_a_renamed_date_field_is_caught(self):
        profile = self.profile_for(self.info)
        changed = dict(self.info)
        changed["filters"] = [flt(column="paramFromDate", control="mskDateFrom"),
                              flt(column="paramToDate", control="mskDateTo"),
                              flt(column="paramPo", control="edtPo")]
        problems = self.p.describe_change(profile, changed)
        self.assertTrue(problems)
        self.assertIn("paramEndDate", problems[0])

    def test_a_missing_grid_is_caught(self):
        profile = self.profile_for(self.info)
        changed = dict(self.info, grids=[grid("grdOther", "dsSomethingElse", 10)])
        self.assertTrue(self.p.describe_change(profile, changed))

    def test_a_control_appearing_or_vanishing_is_not_a_change(self):
        # Unbound inputs are collected only when visible, and visibility moves
        # with scrolling and late-rendering panels. Including them made a
        # screen "change" between two runs seconds apart, so the profile threw
        # itself away every time.
        profile = self.profile_for(self.info)
        scrolled = dict(self.info,
                        unbound=[flt(control="edtLotNo", bound=False)])
        self.assertEqual(self.p.describe_change(profile, scrolled), [])

    def test_the_same_column_on_a_different_control_is_not_a_change(self):
        # One column can be bound to two controls; which one is recorded
        # depends on which was visible.
        profile = self.profile_for(self.info)
        rebound = dict(self.info)
        rebound["filters"] = [flt(column="paramFromDate", control="mskDateFrom2"),
                              flt(column="paramEndDate", control="mskDateTo"),
                              flt(column="paramPo", control="edtPo")]
        self.assertEqual(self.p.describe_change(profile, rebound), [])

    def test_a_second_grid_on_the_same_dataset_is_not_a_change(self):
        # The Excel export leaves a clone (grdPrnMpp__EXCEL__) bound to the
        # same dataset, so the screen "changed" after every export.
        profile = self.profile_for(self.info)
        after_export = dict(self.info,
                            grids=self.info["grids"] +
                            [grid("grdMain__EXCEL__", "dsMasterProdPlan", 0)])
        self.assertEqual(self.p.describe_change(profile, after_export), [])

    def test_a_new_filter_elsewhere_is_reported_not_ignored(self):
        # Nothing the profile uses moved, but it is not the same screen -
        # worth saying so rather than replaying in silence.
        profile = self.profile_for(self.info)
        changed = dict(self.info)
        changed["filters"] = self.info["filters"] + [flt(column="paramNew",
                                                         control="edtNew")]
        self.assertTrue(self.p.describe_change(profile, changed))

    def test_a_saved_reference_never_holds_a_value_or_an_id(self):
        # A form tree contains live session tokens; only named fields are
        # ever copied out.
        ref = self.p.field_ref(flt(column="paramPo", value="011074232146"))
        self.assertNotIn("value", ref)
        self.assertNotIn("id", ref)
        self.assertEqual(set(ref), {"dataset", "column", "control", "form", "label"})


class RememberedValues(unittest.TestCase):
    """A remembered value must survive a run that did not supply one.

    P1111UM00 was recorded with VD and a date range, then run once with
    everything blank, and its memory came back empty. "Never forget" has to
    mean that an empty answer does not erase a remembered one."""

    def setUp(self):
        import gmes_profile
        self.p = gmes_profile
        self.previous = {"values": {"division": "VD", "from": "20260909",
                                    "to": "20260909", "sets": {}}}

    def test_a_blank_run_does_not_erase_anything(self):
        merged = self.p._merge_values(
            self.previous, {"division": "", "from": "", "to": "", "sets": {}})
        self.assertEqual(merged["division"], "VD")
        self.assertEqual(merged["from"], "20260909")

    def test_a_supplied_value_replaces_the_old_one(self):
        merged = self.p._merge_values(
            self.previous, {"division": "MOBILE", "from": "", "to": "", "sets": {}})
        self.assertEqual(merged["division"], "MOBILE")
        self.assertEqual(merged["to"], "20260909")     # untouched

    def test_first_ever_save_keeps_what_it_was_given(self):
        merged = self.p._merge_values(None, {"division": "VD", "from": "20260901",
                                             "to": "20260902", "sets": {}})
        self.assertEqual(merged, {"division": "VD", "from": "20260901",
                                  "to": "20260902", "sets": {}})

    def test_values_are_recovered_from_an_older_profile(self):
        # Profiles written before the values block still carry the command
        # that proved them; re-teaching would be absurd.
        old = {"proved": {"rows": 800,
                          "command": "--division VD --from 20260909 --to 20260909"}}
        self.assertEqual(self.p.last_values(old)["division"], "VD")
        self.assertEqual(self.p.last_values(old)["to"], "20260909")

    def test_none_in_a_recovered_command_is_not_a_value(self):
        old = {"proved": {"command": "--division None --from None --to None"}}
        self.assertEqual(self.p.last_values(old), {})


class GeneratedJavaScript(unittest.TestCase):
    """The JS is built by % substitution, so a stray literal % or a
    miscounted placeholder is a runtime crash inside the browser call rather
    than an import error. Both are cheap to catch here."""

    def snippets(self):
        import gmes_data
        helpers = gmes_data.JS_HELPERS
        vis = "function(el){return true;}"
        return {
            "discover": core._js(core.JS_DISCOVER, helpers, vis, '"P1112UM00"',
                                 '["edt"]', '"btn"'),
            "left_options": core.JS_LEFT_OPTIONS,
            "org_trees": core._js(core.JS_ORG_TREES, helpers),
            "tick_org": core._js(core.JS_TICK_ORG, helpers, '"ds"', '["VD"]',
                                 "true", '"OrgCategory_GDS"'),
            "control_value": core._js(core.JS_CONTROL_VALUE, '"an.id"'),
            "tab_close": core._js(core.JS_TAB_CLOSE_TARGET, vis, '"TAB_win_0_1"'),
            "org_selection": core._js(core.JS_ORG_SELECTION, vis),
        }

    def test_every_template_formats(self):
        for name, js in self.snippets().items():
            self.assertNotIn("%s", js, f"{name} has an unfilled placeholder")

    def test_every_snippet_is_balanced_and_is_an_iife(self):
        for name, js in self.snippets().items():
            for opener, closer in (("{", "}"), ("(", ")"), ("[", "]")):
                self.assertEqual(js.count(opener), js.count(closer),
                                 f"{name} has unbalanced {opener}{closer}")
            self.assertTrue(js.strip().startswith("(function"), name)
            self.assertTrue(js.strip().endswith("})()"), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
