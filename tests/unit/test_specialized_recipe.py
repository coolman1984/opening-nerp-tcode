"""Production Plan policy is an external consumer of generic G-MES."""
import csv
import os
import tempfile
import unittest
from unittest.mock import patch

from gmes.contracts import DatasetPage, RunResult


class ProductionPlanRecipeTests(unittest.TestCase):
    def setUp(self):
        from examples import production_plan_recipe
        self.recipe = production_plan_recipe

    def test_clean_csv_filters_only_po_subtotals(self):
        pages = [DatasetPage(rows=({"poNo": "01", "qty": "2", "_private": "x"},
                                   {"poNo": " ", "qty": "2"}), offset=0, returned=2, total=2)]
        with tempfile.TemporaryDirectory() as directory, patch.object(
                self.recipe.gmes, "read_dataset_pages", return_value=iter(pages)):
            path, written, dropped = self.recipe.export_clean_data(object(), directory, "20260912_010203")
            with open(path, encoding="utf-8-sig", newline="") as handle:
                self.assertEqual(list(csv.DictReader(handle)), [{"poNo": "01", "qty": "2"}])
        self.assertEqual((written, dropped), (1, 1))
        self.assertEqual(self.recipe.production_plan_filename("20260912_010203"),
                         "Production Plan by Order(Line)_20260912_010203.xlsx")

    def test_recipe_uses_generic_run_with_known_policy(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(self.recipe.gmes, "run_screen", return_value=RunResult("P1112UM00", True, rows=4)) as run, \
             patch.object(self.recipe, "export_clean_data", return_value=("clean.csv", 1, 3)):
            result = self.recipe.run_production_plan(object(), date="2026-09-07", out_dir=directory, log=lambda _: None)
        spec = run.call_args.args[1]
        self.assertEqual((spec.screen_code, spec.grid_name, spec.verify),
                         ("P1112UM00", "dsMasterProdPlan", ("planYmd", "20260907")))
        self.assertEqual(result.files, ("clean.csv",))
