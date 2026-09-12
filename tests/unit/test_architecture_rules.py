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
    def test_every_cli_file_imports_only_the_application_facade(self):
        for path in (PACKAGE / "cli").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level:
                    self.assertEqual((node.module, [item.name for item in node.names]),
                                     ("application", ["facade"]), path)
                if isinstance(node, ast.Import):
                    self.assertFalse(any(name.name.startswith("gmes") for name in node.names), path)

    def test_cli_never_operates_a_cdp_or_websocket_session(self):
        forbidden_names = {"connect_gmes", "connect", "create_connection", "websocket"}
        forbidden_methods = {"close", "connect", "create_connection"}
        for path in (PACKAGE / "cli").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    self.assertNotIn(node.id, forbidden_names, path)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, forbidden_methods, path)

    def test_public_facade_never_exposes_infrastructure_handles(self):
        source = (PACKAGE / "application" / "facade.py").read_text(encoding="utf-8").lower()
        for forbidden in ("connect_gmes", "gmes_tab", "websocket", "browser", "read_dataset_pages",
                          "run_screen", "run_many"):
            self.assertNotIn(forbidden, source)

    def test_specialized_consumers_only_use_public_gmes_capabilities(self):
        for path in (ROOT / "examples").rglob("*.py"):
            for name in imports(path):
                self.assertFalse(any(part in name for part in (".browser", ".query", ".screens",
                                                               ".discovery", ".export", ".connect_uc")),
                                 f"{path}: {name}")
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.assertNotIn("ws", [arg.arg for arg in node.args.args], path)

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
        for doctor in PACKAGE.rglob("*doctor*.py"):
            source = doctor.read_text(encoding="utf-8")
            self.assertNotIn("migrate_legacy_credentials", source)
            self.assertNotIn("copy2(", source)
            self.assertNotIn("write_", source)
            tree = ast.parse(source, filename=str(doctor))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
                    self.assertNotIn(name, {"mkdir", "unlink", "write_text", "write_bytes", "copy", "copy2",
                                            "save", "migrate_legacy_credentials"}, doctor)

    def test_project_eye_records_the_enforced_system_map(self):
        for relative in ("PROJECT_EYE.md", "LESSONS.md", ".project-eye/graph.yaml",
                         ".project-eye/rules.yaml", ".project-eye/manifest.json"):
            self.assertTrue((ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main(verbosity=2)
