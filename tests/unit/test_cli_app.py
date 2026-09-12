import unittest
from unittest.mock import patch

from gmes.cli import app
from gmes.contracts import LoginAttempt, LoginOutcome


class CliSmokeTests(unittest.TestCase):
    def test_version_never_connects_to_gmes(self):
        with patch.object(app, "sign_in") as sign_in:
            self.assertEqual(app.main(["version"]), 0)
        sign_in.assert_not_called()

    def test_run_rejects_a_malformed_set_before_sign_in(self):
        with patch.object(app, "sign_in") as sign_in:
            self.assertEqual(app.main(["run", "P1112WM00", "--set", "missing"]), 2)
        sign_in.assert_not_called()

    def test_run_builds_one_typed_spec_per_screen(self):
        with patch.object(app, "sign_in", return_value=LoginAttempt(LoginOutcome.OK)), \
             patch.object(app, "connect_gmes", return_value=type("W", (), {"close": lambda s: None})()), \
             patch.object(app, "run_many", return_value=[] ) as run_many:
            self.assertEqual(app.main(["run", "P1112WM00", "P1113WM00", "--date", "20260912",
                                       "--set", "plant=VD", "--export", "none"]), 0)
        specs = run_many.call_args.args[1]
        self.assertEqual([s.screen_code for s in specs], ["P1112WM00", "P1113WM00"])
        self.assertTrue(all(s.date_from == s.date_to == "20260912" for s in specs))
        self.assertTrue(all(s.sets == {"plant": "VD"} for s in specs))

    def test_data_read_passes_the_named_limit_to_the_reader(self):
        response = {"found": True, "file": "P.xfdl.js", "total": 1,
                    "columns": ["id"], "rows": [{"id": "1"}]}
        with patch.object(app, "sign_in", return_value=LoginAttempt(LoginOutcome.OK)), \
             patch.object(app, "connect_gmes", return_value=type("W", (), {"close": lambda s: None})()), \
             patch.object(app, "read_dataset", return_value=response) as read:
            self.assertEqual(app.main(["data", "read", "P1112WM00", "dsRows", "--limit", "50"]), 0)
        self.assertEqual(read.call_args.kwargs["limit"], 50)


if __name__ == "__main__":
    unittest.main()
