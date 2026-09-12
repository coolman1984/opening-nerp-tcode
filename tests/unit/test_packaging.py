"""Packaging entry points must import the installed package, never a loose module."""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class PackagingTests(unittest.TestCase):
    def test_pyinstaller_entrypoint_imports_the_package_cli(self):
        target = ROOT / "packaging" / "entrypoint.py"
        tree = ast.parse(target.read_text(encoding="utf-8"), filename=str(target))
        imports = [node.module for node in ast.walk(tree)
                   if isinstance(node, ast.ImportFrom)]
        self.assertEqual(imports, ["gmes.cli.app"])

    def test_smoke_removes_python_paths_but_keeps_windows_loader_paths(self):
        source = (ROOT / "packaging" / "smoke.ps1").read_text(encoding="utf-8")
        self.assertIn('$env:PATH = "$env:SystemRoot;$env:SystemRoot\\System32"', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
