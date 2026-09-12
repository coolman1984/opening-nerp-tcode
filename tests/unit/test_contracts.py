"""Offline tests for gmes.contracts - inert data shapes.

Just confirms each contract constructs with representative values and
round-trips through dataclasses.asdict(); these carry no logic of
their own to test more deeply than that.
"""
import dataclasses
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.contracts import (  # noqa: E402
    DatasetPage,
    DatasetResult,
    ExportResult,
    FilterRef,
    GridRef,
    LoginAttempt,
    LoginOutcome,
    OptionRef,
    ProfileDrift,
    ProfileRecord,
    QuickViewRef,
    RunResult,
    RunSpec,
    ScreenInfo,
    TreeRef,
)


def roundtrip(instance):
    return dataclasses.asdict(instance)


class ScreenShapes(unittest.TestCase):
    def test_filter_ref_matches_the_real_discover_dict_keys(self):
        f = FilterRef(dataset="dsFilterDVO", column="paramFromDate",
                      control="mskDateFrom", label="From", form="P1112WF00.xfdl.js",
                      value="20260909", visible=True, kind="Edit",
                      id="win.form.mskDateFrom", bound=True)
        self.assertEqual(roundtrip(f)["column"], "paramFromDate")

    def test_grid_ref(self):
        g = GridRef(name="grdMasterProdPlan", dataset="dsMasterProdPlan",
                    form="P1112WM00.xfdl.js", area=669333, visible=True)
        self.assertEqual(roundtrip(g)["dataset"], "dsMasterProdPlan")

    def test_tree_ref_supports_both_live_discovery_and_a_saved_entry(self):
        live = TreeRef(form="OrgCategory_GDS.xfdl.js",
                       dataset="dsCatCommonTreeNodeDVO", rows=34,
                       settable=True, names=("VD", "MOBILE"), checked=("VD",))
        saved = TreeRef(form="OrgCategory_GDS.xfdl.js",
                        dataset="dsCatCommonTreeNodeDVO", entry="VD")
        self.assertIn("VD", live.names)
        self.assertEqual(saved.entry, "VD")

    def test_option_ref_selected_property_follows_state(self):
        self.assertTrue(OptionRef(label="Plan Date", state="selected").selected)
        self.assertTrue(OptionRef(label="PLANT", state="checked").selected)
        self.assertFalse(OptionRef(label="Create Date", state="not selected").selected)

    def test_quick_view_ref(self):
        qv = QuickViewRef(screen="P1114WM01", name="PO I/F Monitoring", active=False)
        self.assertFalse(qv.active)

    def test_screen_info_holds_everything_together(self):
        info = ScreenInfo(
            code="P1112UM00", title="Production Plan by Order(Line)",
            window="winPPM0219_0_603",
            filters=(FilterRef(dataset="dsFilterDVO", column="paramFromDate",
                               control="mskDateFrom"),),
            grids=(GridRef(name="grdMasterProdPlan", dataset="dsMasterProdPlan"),),
            has_inquiry=True, has_excel=True,
        )
        self.assertEqual(len(info.filters), 1)
        self.assertTrue(info.has_inquiry)


class LoginShapes(unittest.TestCase):
    def test_outcome_members_are_distinct(self):
        self.assertNotEqual(LoginOutcome.FAILED, LoginOutcome.REJECTED)
        self.assertNotEqual(LoginOutcome.OK, LoginOutcome.FAILED)

    def test_login_attempt(self):
        a = LoginAttempt(outcome=LoginOutcome.REJECTED, detail="Auth bad credentials")
        self.assertEqual(a.outcome, LoginOutcome.REJECTED)


class RunShapes(unittest.TestCase):
    def test_run_spec_matches_run_screen_kwarg_names(self):
        spec = RunSpec(screen_code="P1112UM00", division="VD",
                       date_from="20260909", date_to="20260909",
                       sets={"Production Order": "011074232146"},
                       grid_name="dsMasterProdPlan", verify=("planYmd", None))
        self.assertEqual(spec.sets["Production Order"], "011074232146")

    def test_run_result_matches_run_screen_output_keys(self):
        r = RunResult(screen="P1112UM00", ok=True, rows=800,
                      files=("out.xlsx", "out_data.csv"),
                      applied={"paramFromDate": "20260909"})
        self.assertTrue(r.ok)
        self.assertEqual(len(r.files), 2)

    def test_export_result(self):
        e = ExportResult(path="out.xlsx", format="xlsx", row_count=800, checked=True)
        self.assertTrue(e.checked)


class ProfileShapes(unittest.TestCase):
    def test_profile_record_from_to_are_keyword_safe_field_names(self):
        rec = ProfileRecord(
            screen="P1112UM00", division="VD",
            from_ref=FilterRef(dataset="dsFilterDVO", column="paramFromDate",
                               control="mskDateFrom"),
            to_ref=FilterRef(dataset="dsFilterDVO", column="paramEndDate",
                             control="mskDateTo"),
        )
        self.assertEqual(rec.from_ref.column, "paramFromDate")
        self.assertEqual(rec.to_ref.column, "paramEndDate")

    def test_profile_drift_changed_flag(self):
        clean = ProfileDrift(changed=False)
        dirty = ProfileDrift(changed=True, problems=("the 'from' date field is gone",))
        self.assertFalse(clean.changed)
        self.assertEqual(len(dirty.problems), 1)


class DatasetShapes(unittest.TestCase):
    def test_dataset_page_and_result(self):
        page = DatasetPage(rows=({"poNo": "123"},), offset=0, returned=1, total=800)
        result = DatasetResult(columns=("poNo",), rows=page.rows, total=page.total)
        self.assertEqual(result.total, 800)


if __name__ == "__main__":
    unittest.main(verbosity=2)
