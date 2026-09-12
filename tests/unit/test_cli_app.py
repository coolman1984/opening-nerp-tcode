import unittest
from unittest.mock import patch

from gmes.cli import app
from gmes.contracts import DataExecution, LoginAttempt, LoginOutcome, RunExecution


class CliSmokeTests(unittest.TestCase):
    def test_version_never_connects_to_gmes(self):
        with patch.object(app.application, "execute_login") as login:
            self.assertEqual(app.main(["version"]), 0)
        login.assert_not_called()

    def test_run_rejects_a_malformed_set_before_sign_in(self):
        with patch.object(app.application, "execute_run_request", side_effect=ValueError("bad set")) as execute:
            self.assertEqual(app.main(["run", "P1112WM00", "--set", "missing"]), 2)
        execute.assert_called_once()

    def test_run_builds_one_typed_spec_per_screen(self):
        execution = RunExecution(LoginAttempt(LoginOutcome.OK), ())
        with patch.object(app.application, "execute_run_request", return_value=execution) as run:
            self.assertEqual(app.main(["run", "P1112WM00", "P1113WM00", "--date", "20260912",
                                       "--set", "plant=VD", "--export", "none"]), 0)
        self.assertEqual(run.call_args.args[0], ["P1112WM00", "P1113WM00"])
        self.assertEqual(run.call_args.kwargs["date"], "20260912")
        self.assertEqual(run.call_args.kwargs["sets"], ["plant=VD"])

    def test_data_read_passes_the_named_limit_to_the_reader(self):
        response = {"found": True, "file": "P.xfdl.js", "total": 1,
                    "columns": ["id"], "rows": [{"id": "1"}]}
        execution = DataExecution(LoginAttempt(LoginOutcome.OK), response)
        with patch.object(app.application, "execute_data_read", return_value=execution) as read:
            self.assertEqual(app.main(["data", "read", "P1112WM00", "dsRows", "--limit", "50"]), 0)
        self.assertEqual(read.call_args.kwargs["limit"], 50)

    def test_migrate_is_explicit_and_does_not_sign_in(self):
        with patch.object(app.application, "execute_login") as login, \
             patch.object(app.application, "migrate_credentials", return_value="copied") as migrate:
            self.assertEqual(app.main(["migrate"]), 0)
        login.assert_not_called()
        migrate.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
