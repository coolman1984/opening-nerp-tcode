"""Application operations own the G-MES session lifecycle."""
import unittest
from unittest.mock import Mock, patch

from gmes.contracts import DatasetPage, LoginAttempt, LoginOutcome, RunResult, RunSpec


class RuntimeOperationTests(unittest.TestCase):
    def setUp(self):
        from gmes.application import runtime_uc
        self.uc = runtime_uc

    def test_run_rejection_never_acquires_a_connection(self):
        with patch.object(self.uc, "sign_in", return_value=LoginAttempt(LoginOutcome.REJECTED)), \
             patch.object(self.uc, "connect_gmes") as connect:
            result = self.uc.execute_run((RunSpec("P1112UM00"),), log=lambda _: None)
        self.assertFalse(result.ok)
        connect.assert_not_called()

    def test_run_closes_connection_after_the_capability(self):
        ws = Mock()
        expected = [RunResult("P1112UM00", True)]
        with patch.object(self.uc, "sign_in", return_value=LoginAttempt(LoginOutcome.OK)), \
             patch.object(self.uc, "connect_gmes", return_value=ws), \
             patch.object(self.uc, "run_many", return_value=expected):
            result = self.uc.execute_run((RunSpec("P1112UM00"),), log=lambda _: None)
        self.assertEqual(result.results, tuple(expected))
        ws.close.assert_called_once_with()

    def test_request_validation_happens_before_sign_in(self):
        with patch.object(self.uc, "sign_in") as sign_in:
            with self.assertRaises(ValueError):
                self.uc.execute_run_request(["P1112UM00"], sets=["missing"])
        sign_in.assert_not_called()

    def test_data_read_closes_connection_after_the_capability(self):
        ws = Mock()
        response = {"found": True, "rows": []}
        with patch.object(self.uc, "sign_in", return_value=LoginAttempt(LoginOutcome.OK)), \
             patch.object(self.uc, "connect_gmes", return_value=ws), \
             patch.object(self.uc, "read_open_dataset", return_value=response):
            result = self.uc.execute_data_read("P", "ds", limit=50)
        self.assertIs(result.data, response)
        ws.close.assert_called_once_with()

    def test_stream_passes_pages_but_never_a_connection_to_the_consumer(self):
        ws = Mock()
        pages = iter([DatasetPage(rows=({"id": "1"},), offset=0, returned=1, total=1)])
        consume = Mock(return_value="written.csv")
        with patch.object(self.uc, "sign_in", return_value=LoginAttempt(LoginOutcome.OK)), \
             patch.object(self.uc, "connect_gmes", return_value=ws), \
             patch.object(self.uc, "read_dataset_pages", return_value=pages):
            result = self.uc.execute_data_stream("P", "ds", consume)
        self.assertEqual(result.value, "written.csv")
        self.assertIs(consume.call_args.args[0], pages)
        ws.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
