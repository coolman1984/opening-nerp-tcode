"""Offline tests for gmes.discovery.fingerprint - profile-drift detection,
ported from tests/test_gmes_core.py's Profiles class onto the new typed
(FilterRef/GridRef/ScreenInfo) signatures. tests/test_gmes_core.py is left
untouched and still tests the old gmes_core.py/gmes_profile.py directly.

profiles/refs.py (field_ref/grid_ref/tree_ref, which BUILD the persisted
reference dicts used below) has not been ported yet - that is Phase 5f of
the migration - so this file constructs the equivalent plain dicts by
hand, matching gmes_profile.py's known field_ref/grid_ref output shape
({dataset,column,control,form,label} / {name,dataset,form}). The
allowlist test for field_ref itself (proving it never carries a value or
an id) belongs with profiles/refs.py in Phase 5f and is not ported here.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.contracts import FilterRef, GridRef, ScreenInfo  # noqa: E402
from gmes.discovery.fingerprint import describe_change, fingerprint  # noqa: E402


def flt(column="", control="edtThing", bound=True):
    return FilterRef(column=column, control=control, dataset="dsFilterDVO", bound=bound)


def grid(name, dataset, area):
    return GridRef(name=name, dataset=dataset, area=area)


def field_ref(f):
    """Matches gmes_profile.field_ref's exact output shape."""
    return {"dataset": f.dataset, "column": f.column, "control": f.control,
           "form": f.form, "label": f.label}


def grid_ref(g):
    """Matches gmes_profile.grid_ref's exact output shape."""
    return {"name": g.name, "dataset": g.dataset, "form": g.form}


class Profiles(unittest.TestCase):
    """What the tool remembers after a run that worked, and - more
    importantly - when it must refuse to trust that memory."""

    def setUp(self):
        self.info = ScreenInfo(
            code="P1112UM00",
            filters=(flt(column="paramFromDate", control="mskDateFrom"),
                    flt(column="paramEndDate", control="mskDateTo"),
                    flt(column="paramPo", control="edtPo")),
            unbound=(),
            grids=(grid("grdMain", "dsMasterProdPlan", 400000),),
        )

    def profile_for(self, info):
        return {"from": field_ref(info.filters[0]),
                "to": field_ref(info.filters[1]),
                "grid": grid_ref(info.grids[0]),
                "fingerprint": fingerprint(info)}

    def test_an_unchanged_screen_has_no_problems(self):
        self.assertEqual(describe_change(self.profile_for(self.info), self.info), [])

    def test_the_same_screen_fingerprints_the_same_twice(self):
        self.assertEqual(fingerprint(self.info), fingerprint(self.info))

    def test_a_renamed_date_field_is_caught(self):
        profile = self.profile_for(self.info)
        changed = ScreenInfo(
            code=self.info.code,
            filters=(flt(column="paramFromDate", control="mskDateFrom"),
                    flt(column="paramToDate", control="mskDateTo"),
                    flt(column="paramPo", control="edtPo")),
            unbound=self.info.unbound, grids=self.info.grids)
        problems = describe_change(profile, changed)
        self.assertTrue(problems)
        self.assertIn("paramEndDate", problems[0])

    def test_a_missing_grid_is_caught(self):
        profile = self.profile_for(self.info)
        changed = ScreenInfo(
            code=self.info.code, filters=self.info.filters, unbound=self.info.unbound,
            grids=(grid("grdOther", "dsSomethingElse", 10),))
        self.assertTrue(describe_change(profile, changed))

    def test_a_control_appearing_or_vanishing_is_not_a_change(self):
        # Unbound inputs are collected only when visible, and visibility moves
        # with scrolling and late-rendering panels. Including them made a
        # screen "change" between two runs seconds apart, so the profile threw
        # itself away every time.
        profile = self.profile_for(self.info)
        scrolled = ScreenInfo(
            code=self.info.code, filters=self.info.filters,
            unbound=(flt(control="edtLotNo", bound=False),), grids=self.info.grids)
        self.assertEqual(describe_change(profile, scrolled), [])

    def test_the_same_column_on_a_different_control_is_not_a_change(self):
        # One column can be bound to two controls; which one is recorded
        # depends on which was visible.
        profile = self.profile_for(self.info)
        rebound = ScreenInfo(
            code=self.info.code,
            filters=(flt(column="paramFromDate", control="mskDateFrom2"),
                    flt(column="paramEndDate", control="mskDateTo"),
                    flt(column="paramPo", control="edtPo")),
            unbound=self.info.unbound, grids=self.info.grids)
        self.assertEqual(describe_change(profile, rebound), [])

    def test_a_second_grid_on_the_same_dataset_is_not_a_change(self):
        # The Excel export leaves a clone (grdPrnMpp__EXCEL__) bound to the
        # same dataset, so the screen "changed" after every export.
        profile = self.profile_for(self.info)
        after_export = ScreenInfo(
            code=self.info.code, filters=self.info.filters, unbound=self.info.unbound,
            grids=self.info.grids + (grid("grdMain__EXCEL__", "dsMasterProdPlan", 0),))
        self.assertEqual(describe_change(profile, after_export), [])

    def test_a_new_filter_elsewhere_is_reported_not_ignored(self):
        # Nothing the profile uses moved, but it is not the same screen -
        # worth saying so rather than replaying in silence.
        profile = self.profile_for(self.info)
        changed = ScreenInfo(
            code=self.info.code,
            filters=self.info.filters + (flt(column="paramNew", control="edtNew"),),
            unbound=self.info.unbound, grids=self.info.grids)
        self.assertTrue(describe_change(profile, changed))


if __name__ == "__main__":
    unittest.main(verbosity=2)
