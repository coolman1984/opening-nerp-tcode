"""Offline tests for gmes.screens.grids - result-grid selection, ported
from tests/test_gmes_core.py's ChooseGrid/Digits classes onto the new
typed (GridRef/ScreenInfo) signatures. tests/test_gmes_core.py is left
untouched and still tests the old gmes_core.py directly.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.contracts import GridRef, ScreenInfo  # noqa: E402
from gmes.screens import grids as g  # noqa: E402


def grid(name, dataset, area, visible=True, form="P1112WM00.xfdl.js"):
    return GridRef(name=name, dataset=dataset, area=area, visible=visible, form=form)


def info(grids):
    return ScreenInfo(code="P1112UM00", grids=tuple(grids))


class ChooseGrid(unittest.TestCase):
    def test_the_only_grid_wins(self):
        chosen, rivals = g.choose_grid(info([grid("grdMain", "dsMasterProdPlan", 400000)]))
        self.assertEqual(chosen.dataset, "dsMasterProdPlan")
        self.assertEqual(rivals, [])

    def test_a_hidden_grid_is_not_chosen_over_a_visible_one(self):
        i = info([grid("grdHidden", "dsOther", 900000, visible=False),
                 grid("grdMain", "dsMain", 400000)])
        chosen, _ = g.choose_grid(i)
        self.assertEqual(chosen.name, "grdMain")

    def test_a_comparable_second_grid_is_reported_not_hidden(self):
        # Master-detail screens have two. Picking the larger silently is a
        # coin toss, and the wrong side of it exports the wrong data.
        i = info([grid("grdMaster", "dsMaster", 400000),
                 grid("grdDetail", "dsDetail", 380000)])
        chosen, rivals = g.choose_grid(i)
        self.assertEqual(chosen.name, "grdMaster")
        self.assertEqual([r.name for r in rivals], ["grdDetail"])

    def test_a_small_second_grid_is_not_an_ambiguity(self):
        i = info([grid("grdMaster", "dsMaster", 400000),
                 grid("grdTiny", "dsTiny", 9000)])
        _, rivals = g.choose_grid(i)
        self.assertEqual(rivals, [])

    def test_prefer_by_dataset_name_settles_it(self):
        i = info([grid("grdMaster", "dsMaster", 400000),
                 grid("grdDetail", "dsDetail", 380000)])
        chosen, rivals = g.choose_grid(i, prefer="dsDetail")
        self.assertEqual(chosen.name, "grdDetail")
        self.assertEqual(rivals, [])

    def test_an_unmatched_preference_does_not_fall_back_silently(self):
        i = info([grid("grdMaster", "dsMaster", 400000)])
        chosen, rivals = g.choose_grid(i, prefer="dsNoSuchThing")
        self.assertIsNone(chosen)
        self.assertTrue(rivals)

    def test_no_grids_at_all(self):
        self.assertEqual(g.choose_grid(info([])), (None, []))


class Digits(unittest.TestCase):
    def test_a_formatted_date_and_a_raw_one_compare_equal(self):
        self.assertEqual(g.digits_only("2026-09-08"), g.digits_only("20260908"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
