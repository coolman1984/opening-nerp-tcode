"""Mechanical rules for the standalone G-MES architecture checkpoint."""
import ast
import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "gmes"


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(name.name for name in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level + (node.module or "")
            found.append(prefix)
    return found


class ArchitectureRules(unittest.TestCase):
    def test_cli_imports_only_the_application_facade(self):
        project_imports = [name for name in imports(PACKAGE / "cli" / "app.py")
                           if name.startswith(".") or name.startswith("gmes")]
        self.assertEqual(project_imports, ["..application"])

    def test_generic_application_has_no_business_specific_recipe(self):
        self.assertFalse((PACKAGE / "application" / "prodplan_recipe.py").exists())
        for path in PACKAGE.rglob("*.py"):
            source = path.read_text(encoding="utf-8").lower()
            self.assertNotIn("production plan", source, path)
            self.assertNotIn("prodplan", source, path)

    def test_standalone_never_imports_legacy_or_nerp_modules(self):
        forbidden = {"cdp_common", "execute_filters", "export_to_excel", "search_tcode",
                     "run_nerp_workflow", "gmes_core", "gmes_data", "gmes_login",
                     "gmes_open_screen", "gmes_profile", "gmes_report"}
        for path in PACKAGE.rglob("*.py"):
            for name in imports(path):
                self.assertNotIn(name.lstrip("."), forbidden, f"{path}: {name}")

    def test_no_catch_all_modules_or_new_god_modules(self):
        forbidden_stems = {"utils", "common", "helpers"}
        for path in PACKAGE.rglob("*.py"):
            self.assertNotIn(path.stem, forbidden_stems, path)
            self.assertLessEqual(len(path.read_text(encoding="utf-8").splitlines()), 600, path)

    def test_runtime_state_resolves_only_under_localappdata_gmes(self):
        paths_source = (PACKAGE / "paths.py").read_text(encoding="utf-8")
        self.assertIn('APP_NAME = "GMES"', paths_source)
        self.assertIn('Path(os.environ["LOCALAPPDATA"])', paths_source)

    def test_doctor_has_no_migration_or_write_capability(self):
        doctor = PACKAGE / "diagnostics" / "doctor.py"
        if doctor.exists():
            source = doctor.read_text(encoding="utf-8")
            self.assertNotIn("migrate_legacy_credentials", source)
            self.assertNotIn("copy2(", source)
            self.assertNotIn("write_", source)

    def test_project_eye_records_the_enforced_system_map(self):
        for relative in ("PROJECT_EYE.md", "LESSONS.md", ".project-eye/graph.yaml",
                         ".project-eye/rules.yaml", ".project-eye/manifest.json"):
            self.assertTrue((ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main(verbosity=2)
