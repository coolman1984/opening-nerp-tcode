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
from copy import deepcopy
from unittest.mock import patch

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

    def test_date_named_columns_offers_real_candidates_before_any_rows_exist(self):
        # This is what the --verify question hint uses before Inquiry has
        # ever run: no row values exist yet to confirm a date SHAPE, only
        # the dataset's own column names - so naming is all there is to go
        # on, and it must still exclude internal (_-prefixed) columns and
        # non-date look-alikes.
        columns = ["planYmd", "prodTime", "_rowType", "createDate", "poNo"]
        self.assertEqual(core.date_named_columns(columns), ["planYmd", "createDate"])


class InquirySettleTracker(unittest.TestCase):
    """The settle-decision core of poll_inquiry(). Two live findings shaped
    this (HISTORY.md Phase 65.2): replaying M4131UM00 with the same
    division right after recording it produced the same correct 10-row
    answer, and a direct trace of the poll loop proved the count did not
    merely fail to differ from the pre-click snapshot - it never changed
    on ANY single poll, 17+ seconds straight, with no other observable
    signal available on that screen. An unconfirmed-but-genuinely-stable
    count must still settle eventually - just with more patience than a
    confirmed one, not a five-minute failure on a result that was correct
    the whole time."""

    SETTLE = 4
    UNCONFIRMED = 12   # InquirySettle's default: settle_checks * 3

    def feed(self, before, polls, settle_checks=None, unconfirmed=None):
        """`before` is the pre-click snapshot; `polls` are the readings fed
        one per poll. Returns the settled count, or None if the sequence
        never settles."""
        tracker = core.InquirySettle(
            before, settle_checks=settle_checks or self.SETTLE,
            unconfirmed_settle_checks=unconfirmed)
        for count in polls:
            settled = tracker.step(count)
            if settled is not None:
                return settled
        return None

    def test_a_confirmed_change_settles_after_settle_checks_matches(self):
        # before=0, count changes to 875 and holds - needs settle_checks+1
        # matching reads (the arrival plus settle_checks repeats).
        self.assertIsNone(self.feed(0, [875] * self.SETTLE))
        self.assertEqual(self.feed(0, [875] * (self.SETTLE + 1)), 875)

    def test_an_unconfirmed_stable_count_still_settles_but_needs_more_reads(self):
        # before=10 - the live-traced case: the count never once differs
        # from `before` or from the previous poll. settle_checks alone is
        # not enough...
        self.assertIsNone(self.feed(10, [10] * (self.SETTLE + 1)))
        # ...but it does settle, given the longer unconfirmed threshold.
        self.assertEqual(self.feed(10, [10] * (self.UNCONFIRMED + 1)), 10)

    def test_stable_zeros_never_settle(self):
        # Nexacro clears the dataset the instant Inquiry is pressed; a
        # count stable at zero is a round trip in progress, not an answer -
        # true regardless of confirmed/unconfirmed, or how long it waits.
        self.assertIsNone(self.feed(0, [0] * 30))

    def test_a_count_that_never_stabilizes_never_settles(self):
        # Genuinely erratic - never the same value twice in a row - must
        # not be mistaken for settled just because time passed.
        self.assertIsNone(self.feed(0, list(range(1, 14))))


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


class IsPureNumber(unittest.TestCase):
    """`verify_rows()` and `apply()`'s did-it-take check both used to decide
    "compare by digits alone" on nothing more than "the text contains a
    digit somewhere" - which made digits_only("MODEL-A1") ==
    digits_only("MODEL-B1") (both "1") report a wrong value as verified,
    and a filter that silently landed as the wrong code as having "taken"
    correctly. Only a value that is ENTIRELY digits and separators may be
    reduced to its digits."""

    def test_dates_and_plain_numbers_are_pure(self):
        for text in ("20260908", "2026-09-08", "2026/09/08", "12:30", "011074232146"):
            self.assertTrue(core.is_pure_number(text), text)

    def test_an_alphanumeric_code_is_not_pure_even_with_a_digit_in_it(self):
        for text in ("MODEL-A1", "MODEL-B1", "SM-A137F", "P1112UM00"):
            self.assertFalse(core.is_pure_number(text), text)

    def test_the_exact_collision_that_was_silently_accepted(self):
        # digits_only alone cannot tell these apart - is_pure_number must
        # keep them off that path entirely.
        self.assertEqual(core.digits_only("MODEL-A1"), core.digits_only("MODEL-B1"))
        self.assertFalse(core.is_pure_number("MODEL-A1"))
        self.assertFalse(core.is_pure_number("MODEL-B1"))

    def test_verify_rows_rejects_a_different_alphanumeric_value(self):
        result = {"found": True, "columns": ["modelCode"],
                  "rows": [{"modelCode": "MODEL-B1"}]}
        with patch.object(core, "read_rows", return_value=result):
            seen, problem = core.verify_rows(None, "F", "DS", "modelCode", "MODEL-A1")
        self.assertIsNotNone(problem)
        self.assertIn("MODEL-A1", problem)


class ValuesMatch(unittest.TestCase):
    """values_match() is the shared comparison for verify_rows(), apply()
    and type_text(). Checking only ONE side's shape was not enough, and
    this project shipped that mistake twice: is_pure_number(expected)
    alone let MODEL-B1 verify against an expected MODEL-A1, and checking
    only the WANTED side the other way let a wanted "123" silently accept
    an actual "X123" - confirmed live, verify_rows(..., "123") against a
    row holding "X123" returned problem=None before this fix."""

    def test_both_sides_must_be_numbers_to_compare_as_digits(self):
        self.assertTrue(core.values_match("2026-09-08", "20260908"))
        self.assertFalse(core.values_match("MODEL-A1", "MODEL-B1"))

    def test_a_pure_wanted_value_does_not_silently_accept_an_alphanumeric_actual(self):
        # The exact live-reproduced mirror bug: "123" alone looks like a
        # number worth reducing to digits, but "X123" does not - so they
        # must NOT be compared as digits.
        self.assertFalse(core.values_match("123", "X123"))
        self.assertFalse(core.values_match("X123", "123"))

    def test_exact_text_still_matches_case_insensitively(self):
        self.assertTrue(core.values_match("ABC", "abc"))
        self.assertFalse(core.values_match("ABC", "XYZ"))

    def test_verify_rows_rejects_a_pure_expected_value_against_an_alphanumeric_row(self):
        result = {"found": True, "columns": ["poNo"], "rows": [{"poNo": "X123"}]}
        with patch.object(core, "read_rows", return_value=result):
            seen, problem = core.verify_rows(None, "F", "DS", "poNo", "123")
        self.assertIsNotNone(problem)
        self.assertIn("123", problem)


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


class ProfileReplayLifecycle(unittest.TestCase):
    """A left-panel option creates a second valid screen shape.

    The pre-d7886cd core saved only the post-option shape, then compared it
    with the next opening shape before reapplying the option and refused a
    valid replay.
    """

    class FakeScreen:
        def __init__(self, opening, after_option):
            self._info = opening
            self.after_option = after_option
            self.title = "Profile lifecycle"
            self.menu_id = "M-1"
            self.win_id = "win_1"
            self.warnings = []
            self.last_tree = None
            self.options_set = []

        @property
        def info(self):
            return self._info

        @property
        def filters(self):
            return self.info["filters"]

        @property
        def unbound(self):
            return self.info.get("unbound", [])

        def grid(self, _preferred=None):
            return self.info["grids"][0]

        def set_option(self, label):
            self.options_set.append(label)
            self._info = self.after_option
            return label

        def clear_stale(self, _keep):
            return []

        def inquiry(self, _grid):
            return 1

    def test_option_profile_checks_opening_then_post_option_shape_and_refuses_real_opening_drift(self):
        import gmes_profile

        opening = {"filters": [flt(column="initialDate", control="mskInitial")],
                   "unbound": [], "grids": [grid("grdInitial", "dsInitial", 100)]}
        post_option = {"filters": [flt(column="planDate", control="mskPlan")],
                       "unbound": [], "grids": [grid("grdPlan", "dsPlan", 100)]}
        changed_opening = {"filters": [flt(column="changedDate", control="mskChanged")],
                           "unbound": [], "grids": [grid("grdInitial", "dsInitial", 100)]}
        learned = self.FakeScreen(opening, post_option)
        replay = self.FakeScreen(opening, post_option)
        drifted = self.FakeScreen(changed_opening, post_option)

        store = {}

        def load_profile(code):
            return store.get(code)

        def save_profile(code, _title, _menu_id, info, *, grid=None, options=(),
                         opening_info=None, **_unused):
            store[code] = {
                "fingerprint": gmes_profile.fingerprint(info),
                "opening_fingerprint": gmes_profile.fingerprint(opening_info or info),
                "grid": gmes_profile.grid_ref(grid),
                "options": list(options),
            }
            return "test-profile.json"

        with patch.object(gmes_profile, "load", side_effect=load_profile), \
             patch.object(gmes_profile, "save", side_effect=save_profile) as save, \
             patch.object(core, "open_screen", side_effect=[learned, replay, drifted]), \
             patch.object(core, "org_selection", return_value={"found": False}):
            first = core.run_screen(None, "P1234UM00", options=("Plan Date",),
                                    export="none", log=lambda _message: None)
            self.assertTrue(first["ok"])
            self.assertEqual(store["P1234UM00"]["opening_fingerprint"],
                             gmes_profile.fingerprint(opening))
            self.assertEqual(store["P1234UM00"]["fingerprint"],
                             gmes_profile.fingerprint(post_option))

            second = core.run_screen(None, "P1234UM00", export="none", log=lambda _message: None)
            self.assertTrue(second["ok"])
            self.assertEqual(replay.options_set, ["Plan Date"])
            self.assertEqual(store["P1234UM00"]["grid"]["dataset"], "dsPlan")

            before_failed_replay = deepcopy(store["P1234UM00"])
            with self.assertRaisesRegex(RuntimeError, "remembered screen shape changed"):
                core.run_screen(None, "P1234UM00", export="none", log=lambda _message: None)
            self.assertEqual(drifted.options_set, [])
            self.assertEqual(store["P1234UM00"], before_failed_replay)
            self.assertEqual(save.call_count, 2)


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
            "org_trees": core._js(core.JS_ORG_TREES, helpers, '"P1112UM00"'),
            "alert_text": core._js(core.JS_ALERT_TEXT, helpers, '"P1112UM00"'),
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
