"""Session navigation waits on G-MES state rather than a blind delay."""
import unittest
from unittest.mock import patch


class SessionRuntimeTests(unittest.TestCase):
    def test_open_gmes_rechecks_the_named_tab_without_fixed_sleep(self):
        from gmes.auth import session
        tab = {"url": "http://seegmes4.sec.samsung.net/mes4"}
        with patch.object(session, "gmes_tab", side_effect=[None, tab]) as find, \
             patch.object(session, "navigate_page") as navigate, \
             patch.object(session.time, "sleep") as sleep:
            self.assertIs(session.open_gmes(), tab)
        navigate.assert_called_once()
        self.assertEqual(find.call_count, 2)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
