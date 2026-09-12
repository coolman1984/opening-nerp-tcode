"""Offline tests for gmes.screens.filters - date parsing/matching, ported
from tests/test_gmes_core.py's Words/DateDetection/DateTargets/DateWidth/
NormaliseDate/MatchFilter/DateColumnNaming classes onto the new typed
(FilterRef/ScreenInfo) signatures. tests/test_gmes_core.py is left
untouched and still tests the old gmes_core.py directly.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.contracts import FilterRef, ScreenInfo  # noqa: E402
from gmes.screens import filters as f  # noqa: E402


def flt(column="", label="", control="edtThing", value="", visible=True,
        bound=True, dataset="dsFilterDVO", form="P1112WF00.xfdl.js"):
    return FilterRef(column=column, label=label, control=control, value=value,
                     visible=visible, bound=bound, dataset=dataset, form=form,
                     id="win_0_1.form." + control)


def info(filters=(), unbound=()):
    return ScreenInfo(code="P1112UM00", filters=tuple(filters), unbound=tuple(unbound))


class Words(unittest.TestCase):
    def test_splits_camel_case(self):
        self.assertEqual(f.words("paramFromDate"), {"param", "from", "date"})

    def test_splits_underscores_and_digits(self):
        self.assertIn("checked", f.words("_checked"))

    def test_vendor_code_does_not_contain_the_word_end(self):
        self.assertNotIn("end", f.words("paramVendorCode"))


class DateDetection(unittest.TestCase):
    def test_named_date_column_is_a_date(self):
        self.assertTrue(f.is_date_field(flt(column="paramFromDate")))

    def test_ymd_and_ym_are_dates(self):
        self.assertTrue(f.is_date_field(flt(column="planYmd")))
        self.assertTrue(f.is_date_field(flt(column="stdYm")))

    def test_masked_control_holding_eight_digits_is_a_date(self):
        self.assertTrue(f.is_date_field(
            flt(column="paramPeriod1", control="mskDateFrom", value="20260908")))

    def test_an_eight_digit_code_in_a_text_box_is_not_a_date(self):
        self.assertFalse(f.is_date_field(
            flt(column="paramVendorCode", control="edtVendor", value="10748321")))

    def test_a_label_naming_a_date_is_enough(self):
        self.assertTrue(f.is_date_field(
            flt(column="paramP1", control="mskP1", label="Plan Date")))


class DateTargets(unittest.TestCase):
    def test_finds_a_from_to_pair(self):
        i = info([flt(column="paramFromDate"), flt(column="paramEndDate"),
                 flt(column="paramPo", control="edtPo")])
        frm, to, singles = f.date_targets(i)
        self.assertEqual(frm.column, "paramFromDate")
        self.assertEqual(to.column, "paramEndDate")
        self.assertEqual(singles, [])

    def test_a_screen_with_one_date_reports_it_as_a_single(self):
        i = info([flt(column="planYmd")])
        frm, to, singles = f.date_targets(i)
        self.assertIsNone(frm)
        self.assertIsNone(to)
        self.assertEqual([s.column for s in singles], ["planYmd"])

    def test_a_vendor_code_is_never_the_end_date(self):
        i = info([flt(column="paramFromDate"),
                  flt(column="paramVendorCode", control="edtVendor", value="10748321")])
        frm, to, _ = f.date_targets(i)
        self.assertEqual(frm.column, "paramFromDate")
        self.assertIsNone(to)


class DateWidth(unittest.TestCase):
    def test_full_date_into_an_empty_field(self):
        self.assertEqual(f.fit_date_to_field("20260908", ""), "20260908")

    def test_month_field_gets_six_digits(self):
        self.assertEqual(f.fit_date_to_field("20260908", "202608"), "202609")

    def test_year_field_gets_four(self):
        self.assertEqual(f.fit_date_to_field("20260908", "2025"), "2026")

    def test_a_formatted_existing_value_still_counts_as_eight(self):
        self.assertEqual(f.fit_date_to_field("20260908", "2026-08-01"), "20260908")


class NormaliseDate(unittest.TestCase):
    def test_accepts_the_ways_people_type_it(self):
        for raw in ("20260907", "2026-09-07", "2026/09/07", " 2026.09.07 "):
            self.assertEqual(f.normalise_date(raw), "20260907")

    def test_blank_is_none_not_an_error(self):
        self.assertIsNone(f.normalise_date(""))
        self.assertIsNone(f.normalise_date(None))

    def test_rejects_a_date_that_does_not_exist(self):
        with self.assertRaises(ValueError):
            f.normalise_date("20260231")

    def test_rejects_a_partial_date_rather_than_guessing(self):
        with self.assertRaises(ValueError):
            f.normalise_date("2026-09")


class MatchFilter(unittest.TestCase):
    def setUp(self):
        self.info = info(
            [flt(column="paramPo", label="Production Order", control="edtPo"),
             flt(column="paramFromDate", label="Plan Date", control="mskDateFrom"),
             flt(column="paramTecoYn", label="TECO", control="cboTeco")],
            unbound=[flt(column="", label="Lot", control="edtLotNo", bound=False)])

    def test_by_column(self):
        self.assertEqual(f.match_filter(self.info, "paramPo").control, "edtPo")

    def test_by_label_case_insensitively(self):
        self.assertEqual(f.match_filter(self.info, "production order").column,
                         "paramPo")

    def test_by_control_name(self):
        self.assertEqual(f.match_filter(self.info, "cboTeco").column, "paramTecoYn")

    def test_an_unbound_control_is_reachable_by_name(self):
        found = f.match_filter(self.info, "Lot")
        self.assertEqual(found.control, "edtLotNo")
        self.assertFalse(found.bound)

    def test_unknown_name_returns_none(self):
        self.assertIsNone(f.match_filter(self.info, "nothing like this"))

    def test_ambiguous_partial_returns_every_candidate(self):
        i = info([flt(column="paramFromDate", label="Plan Date"),
                 flt(column="paramEndDate", label="Plan Date To")])
        found = f.match_filter(i, "date")
        self.assertIsInstance(found, list)
        self.assertEqual(len(found), 2)


class DateColumnNaming(unittest.TestCase):
    """A result column is only reported as a date when it is NAMED like one."""

    def named_like_a_date(self, column):
        return bool(f.words(column) & f._DATE_WORDS)

    def test_real_date_columns(self):
        for column in ("planYmd", "createDate", "workDt", "stdYm"):
            self.assertTrue(self.named_like_a_date(column), column)

    def test_look_alikes_are_not_dates(self):
        for column in ("prodTime", "planWeekno", "modelDesc", "poNo"):
            self.assertFalse(self.named_like_a_date(column), column)


if __name__ == "__main__":
    unittest.main(verbosity=2)
