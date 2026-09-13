"""Production Plan policy is an external consumer of generic G-MES."""
import csv
import os
import tempfile
import unittest
from unittest.mock import patch

from gmes.contracts import LoginAttempt, LoginOutcome, RunExecution, RunResult


class ProductionPlanRecipeTests(unittest.TestCase):
    def setUp(self):
        from examples import production_plan_recipe
        self.recipe = production_plan_recipe

    def test_clean_csv_filters_only_po_subtotals(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "generic.csv")
            with open(source, "w", encoding="utf-8-sig", newline="") as handle:
                handle.write("poNo,qty,_private\r\n01,2,x\r\n ,2,ignored\r\n")
            path, written, dropped = self.recipe.export_clean_data(source, directory, "20260912_010203")
            with open(path, encoding="utf-8-sig", newline="") as handle:
                self.assertEqual(list(csv.DictReader(handle)), [{"poNo": "01", "qty": "2", "_private": "x"}])
        self.assertEqual((written, dropped), (1, 1))
        self.assertEqual(self.recipe.production_plan_filename("20260912_010203"),
                         "Production Plan by Order(Line)_20260912_010203.xlsx")

    def test_recipe_uses_generic_run_with_known_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            generic_csv = os.path.join(directory, "generic.csv")
            generic_xlsx = os.path.join(directory, "generic.xlsx")
            with open(generic_csv, "w", encoding="utf-8-sig", newline="") as handle:
                handle.write("poNo,qty\r\n01,2\r\n\r\n")
            with open(generic_xlsx, "wb") as handle:
                handle.write(b"PK\x03\x04" + b"x" * 508)
            with \
             patch.object(self.recipe.gmes, "execute_run", return_value=RunExecution(
                 LoginAttempt(LoginOutcome.OK), (RunResult("P1112UM00", True, rows=1,
                                                            files=(generic_xlsx, generic_csv)),))) as run:
                result = self.recipe.run_production_plan(date="2026-09-07", out_dir=directory, log=lambda _: None)
        spec = run.call_args.args[0][0]
        self.assertEqual((spec.screen_code, spec.grid_name, spec.verify),
                         ("P1112UM00", "dsMasterProdPlan", ("planYmd", "20260907")))
        self.assertEqual(len(result.files), 2)
        self.assertTrue(any(path.endswith("_data.csv") for path in result.files))
        self.assertTrue(any(path.endswith(".xlsx") for path in result.files))
