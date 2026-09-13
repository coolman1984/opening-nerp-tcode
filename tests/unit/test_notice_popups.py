"""What may be closed while a report screen is open, and what may not."""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.nexacro import popups


def popup(name, frame="mainframe.portalFrame.thing", identifier="x"):
    return {"name": name, "frame": frame, "id": identifier, "x": 10.0, "y": 20.0}


class ClassificationTests(unittest.TestCase):
    def test_the_korean_and_english_notice_windows_are_both_recognised(self):
        for title in ("공지사항", "Notice Board", "S9502UP01", "알림"):
            with self.subTest(title=title):
                self.assertEqual(popups.classify(popup(title)), "notice")

    def test_a_notice_is_recognised_from_its_frame_when_the_bar_has_no_text(self):
        self.assertEqual(
            popups.classify(popup("", frame="mainframe.portalFrame.공지사항")), "notice")

    def test_the_export_dialog_is_never_a_notice(self):
        for title in ("Save to Excel", "엑셀 다운로드", "Download"):
            with self.subTest(title=title):
                self.assertEqual(popups.classify(popup(title)), "dialog")

    def test_an_unrecognised_popup_stays_unknown_rather_than_being_guessed(self):
        self.assertEqual(popups.classify(popup("Approval Request")), "unknown")


class CloseNoticesTests(unittest.TestCase):
    """The run-time closer. Only a popup it can name is ever clicked."""

    def setUp(self):
        self.clicked = []
        self.enterContext(patch.object(
            popups, "click_element_by_rect",
            side_effect=lambda ws, x, y: self.clicked.append((x, y))))

    def find_returns(self, *rounds):
        """Each call to find_child_popups answers with the next round."""
        answers = [{"count": len(items),
                    "popups": [dict(item, kind=popups.classify(item)) for item in items]}
                   for items in rounds]
        return patch.object(popups, "find_child_popups", side_effect=answers)

    def test_a_notice_is_closed_and_the_export_dialog_is_left_alone(self):
        notice, dialog = popup("공지사항", identifier="n1"), popup("Save to Excel", identifier="d1")
        with self.find_returns([notice, dialog], [dialog], [dialog]):
            closed, left = popups.close_notices(object())
        self.assertEqual(closed, ["공지사항"])
        self.assertEqual(self.clicked, [(10.0, 20.0)])
        self.assertIn("Save to Excel (dialog)", left)

    def test_an_unrecognised_popup_is_reported_and_never_clicked(self):
        with self.find_returns([popup("Approval Request")]):
            closed, left = popups.close_notices(object())
        self.assertEqual(closed, [])
        self.assertEqual(self.clicked, [])
        self.assertIn("Approval Request (unknown)", left)

    def test_nothing_on_screen_is_neither_a_click_nor_a_complaint(self):
        with self.find_returns([]):
            self.assertEqual(popups.close_notices(object()), ([], []))
        self.assertEqual(self.clicked, [])

    def test_close_dialogs_dismisses_our_own_dialog_and_leaves_a_notice_standing(self):
        dialog, notice = popup("Save to Excel", identifier="d1"), popup("공지사항", identifier="n1")
        with self.find_returns([dialog, notice], [notice], [notice]):
            closed, left = popups.close_dialogs(object())
        self.assertEqual(closed, ["Save to Excel"])
        self.assertIn("공지사항 (notice)", left)

    def test_close_dialogs_never_touches_a_window_it_cannot_name(self):
        with self.find_returns([popup("Approval Request")]):
            closed, left = popups.close_dialogs(object())
        self.assertEqual(closed, [])
        self.assertEqual(self.clicked, [])
        self.assertIn("Approval Request (unknown)", left)


class StubbornPopupTests(unittest.TestCase):
    """A close button that is visible and simply not receiving the click."""

    def setUp(self):
        self.notice = popup("공지사항", frame="mainframe.portalFrame.공지사항", identifier="n1")
        self.enterContext(patch.object(popups, "click_element_by_rect"))

    def test_the_frames_own_close_is_used_when_the_click_does_not_land(self):
        # Present after the click, gone after Nexacro's own close().
        answers = [{"count": 1, "popups": [dict(self.notice, kind="notice")]},
                   {"count": 0, "popups": []}]
        with patch.object(popups, "find_child_popups", side_effect=answers), \
             patch.object(popups, "evaluate", return_value={"closed": True}) as api:
            self.assertEqual(popups._close_one(object(), self.notice, settle=0), "closed through Nexacro")
        self.assertIn(json.dumps("mainframe.portalFrame.공지사항"), api.call_args.args[1])

    def test_a_popup_that_survives_both_attempts_is_reported_not_assumed_gone(self):
        still_there = {"count": 1, "popups": [dict(self.notice, kind="notice")]}
        with patch.object(popups, "find_child_popups", return_value=still_there), \
             patch.object(popups, "evaluate", return_value={"closed": False, "reason": "no close()"}):
            self.assertEqual(popups._close_one(object(), self.notice, settle=0), "")

    def test_close_notices_stops_instead_of_clicking_a_stuck_popup_forever(self):
        still_there = {"count": 1, "popups": [dict(self.notice, kind="notice")]}
        with patch.object(popups, "find_child_popups", return_value=still_there), \
             patch.object(popups, "evaluate", return_value={"closed": False, "reason": "no close()"}):
            closed, left = popups.close_notices(object(), delay=0, settle=0)
        self.assertEqual(closed, [])
        self.assertEqual(left, ["공지사항 (would not close)"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
