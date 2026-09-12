"""Offline tests for standalone profile references, storage, and drift.

These use a temporary LOCALAPPDATA and synthetic screen metadata only.  They
must never create a real user profile, inspect a browser, or serialize a live
Nexacro response.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.contracts import FilterRef, GridRef, ScreenInfo, TreeRef  # noqa: E402
from gmes.profiles import (  # noqa: E402
    _merge_values,
    describe_change,
    field_ref,
    forget,
    grid_ref,
    known,
    last_values,
    load,
    save,
    tree_ref,
)


def filter_ref(column, control):
    return FilterRef(dataset="dsFilterDVO", column=column, control=control,
                     form="P1112WF00.xfdl.js", label="Date",
                     value="must-not-persist", id="generated-id")


def sample_info():
    return ScreenInfo(
        code="P1112UM00",
        filters=(filter_ref("paramFromDate", "mskFrom"),
                 filter_ref("paramEndDate", "mskTo")),
        grids=(GridRef(name="grdMain", dataset="dsMaster", form="P1112WM00.xfdl.js"),),
    )


class ReferenceRedaction(unittest.TestCase):
    def test_only_stable_allowlisted_reference_names_are_persistable(self):
        field = field_ref(filter_ref("paramFromDate", "mskFrom"))
        grid = grid_ref(GridRef(name="grdMain", dataset="dsMaster",
                                form="P1112WM00.xfdl.js", area=400000))
        tree = tree_ref(TreeRef(form="Org.xfdl.js", dataset="dsOrg", entry="VD"))

        self.assertEqual(set(field), {"dataset", "column", "control", "form", "label"})
        self.assertEqual(set(grid), {"name", "dataset", "form"})
        self.assertEqual(set(tree), {"form", "dataset", "entry"})
        serialized = json.dumps({"field": field, "grid": grid, "tree": tree})
        for forbidden in ("must-not-persist", "generated-id", "token", "credential"):
            self.assertNotIn(forbidden, serialized)


class ProfileStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {"LOCALAPPDATA": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def _save(self, code="P1112UM00", title="Production Plan"):
        info = sample_info()
        return save(
            code, title, "P1112UM00", info,
            from_ref=field_ref(info.filters[0]), to_ref=field_ref(info.filters[1]),
            division=tree_ref("Org.xfdl.js", "dsOrg", "VD"), grid=info.grids[0],
            rows=17, command="--division VD --from 20260909 --to 20260909",
            values={"division": "VD", "from": "20260909", "to": "20260909", "sets": {}},
        )

    def test_save_load_known_and_forget_use_localappdata_profiles(self):
        saved = self._save()
        self.assertEqual(saved, Path(self.tmp.name) / "GMES" / "profiles" / "P1112UM00.json")
        self.assertTrue(saved.is_file())
        self.assertEqual(load("p1112um00")["grid"]["dataset"], "dsMaster")
        self.assertEqual([profile["screen"] for profile in known()], ["P1112UM00"])
        self.assertTrue(forget("P1112UM00"))
        self.assertIsNone(load("P1112UM00"))
        self.assertFalse(forget("P1112UM00"))

    def test_known_sorts_newest_first_and_skips_invalid_json(self):
        first = self._save("P1112UM00", "Older")
        older = load("P1112UM00")
        older["learned"] = "2026-09-01 00:00:00"
        first.write_text(json.dumps(older), encoding="utf-8")
        self._save("M4151UM00", "Newer")
        (first.parent / "not-a-profile.json").write_text("{", encoding="utf-8")
        self.assertEqual([profile["screen"] for profile in known()],
                         ["M4151UM00", "P1112UM00"])

    def test_save_rejects_drive_relative_screen_codes(self):
        with self.assertRaises(ValueError):
            self._save("C:outside")

    def test_save_rejects_rooted_screen_codes(self):
        for code in ("C:\\outside", "\\outside", "/outside"):
            with self.subTest(code=code):
                with self.assertRaises(ValueError):
                    self._save(code)


class RememberedValuesAndDrift(unittest.TestCase):
    def test_blank_values_do_not_erase_previous_values(self):
        previous = {"values": {"division": "VD", "from": "20260909",
                               "to": "20260909", "sets": {"Plant": "P703"}}}
        self.assertEqual(
            _merge_values(previous, {"division": "", "from": "", "to": "", "sets": {}}),
            previous["values"],
        )

    def test_old_profiles_recover_values_from_the_proved_command(self):
        old = {"proved": {"command": "--division VD --from 20260909 --to 20260910"}}
        self.assertEqual(last_values(old), {"division": "VD", "from": "20260909",
                                            "to": "20260910", "sets": {}})

    def test_drift_refuses_replay_when_a_saved_reference_has_vanished(self):
        info = sample_info()
        profile = {
            "from": field_ref(info.filters[0]),
            "to": field_ref(info.filters[1]),
            "grid": grid_ref(info.grids[0]),
            "fingerprint": "not-used-when-reference-is-gone",
        }
        changed = ScreenInfo(code=info.code, filters=(info.filters[0],), grids=info.grids)
        problems = describe_change(profile, changed)
        self.assertTrue(problems)
        self.assertIn("paramEndDate", problems[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
