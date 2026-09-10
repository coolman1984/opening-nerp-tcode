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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
