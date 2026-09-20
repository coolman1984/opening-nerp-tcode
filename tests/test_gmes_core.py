"""
Offline tests for the parts of gmes_core.py that do not need a browser.

There is no mock for G-MES (CLAUDE.md 4.3), so the browser-driven half is
verified against the live system by hand. What CAN be tested offline is every
decision the core makes about a screen it has already read: which control a
name refers to, which field is a date, which grid holds the results, how wide
a date to write. Those are exactly the decisions whose failures are silent -
a filter matched to the wrong control, an eight-digit code mistaken for a
date - so each case below is one of those failures.

    python tests/test_gmes_core.py
"""
import json
import os
import re
import sys
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gmes_core as core  # noqa: E402
import gmes_data  # noqa: E402


def _relative_path(path):
    """Python mirror of JS_DISCOVER's own relativePath(): strips everything
    up to and including the renumbered win*_N_NNN segment, so a fixture's
    default stable_path is derived the same way the real discovery computes
    one, rather than an independently-typed guess."""
    parts = path.split(".")
    for i, part in enumerate(parts):
        if re.fullmatch(r"win.*_\d+_\d+", part):
            return ".".join(parts[i + 1:])
    return path


def flt(column="", label="", control="edtThing", value="", visible=True,
        bound=True, dataset="dsFilterDVO", form="P1112WF00.xfdl.js",
        path="application.mainframe.winTest_0_1.form.divBasic.form",
        stable_path=None):
    return {"column": column, "label": label, "control": control, "value": value,
            "visible": visible, "bound": bound, "dataset": dataset, "form": form,
            "id": "win_0_1.form." + control, "kind": "", "path": path,
            "stable_path": stable_path if stable_path is not None else _relative_path(path)}


def grid(name, dataset, area, visible=True, form="P1112WM00.xfdl.js",
         path="application.mainframe.winTest_0_1.form.divResult.form",
         stable_path=None):
    return {"name": name, "dataset": dataset, "area": area, "visible": visible,
            "stable_path": (stable_path if stable_path is not None
                           else _relative_path(path)),
            "form": form, "path": path}


class _FakeClock:
    """A clock that only moves when the code sleeps - keeps a deadline-poll
    loop deterministic and instant instead of busy-spinning for real wall
    time (mirrors tests/test_legacy_hardening.py's own copy)."""

    def __init__(self, start=1000.0):
        self.now = start

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(seconds, 0.01)


class Words(unittest.TestCase):
    def test_splits_camel_case(self):
        self.assertEqual(core.words("paramFromDate"), {"param", "from", "date"})

    def test_splits_underscores_and_digits(self):
        self.assertIn("checked", core.words("_checked"))

    def test_vendor_code_does_not_contain_the_word_end(self):
        # "paramVendorCode" contains the letters "end". A substring match
        # classified it as the period's end date.
        self.assertNotIn("end", core.words("paramVendorCode"))


class DateDetection(unittest.TestCase):
    def test_named_date_column_is_a_date(self):
        self.assertTrue(core.is_date_field(flt(column="paramFromDate")))

    def test_ymd_and_ym_are_dates(self):
        self.assertTrue(core.is_date_field(flt(column="planYmd")))
        self.assertTrue(core.is_date_field(flt(column="stdYm")))

    def test_masked_control_holding_eight_digits_is_a_date(self):
        self.assertTrue(core.is_date_field(
            flt(column="paramPeriod1", control="mskDateFrom", value="20260908")))

    def test_an_eight_digit_code_in_a_text_box_is_not_a_date(self):
        # A Production Order is 12 digits, a vendor code can be 8. Treating
        # the shape of the value as proof would silently overwrite one with
        # today's date.
        self.assertFalse(core.is_date_field(
            flt(column="paramVendorCode", control="edtVendor", value="10748321")))

    def test_a_label_naming_a_date_is_enough(self):
        self.assertTrue(core.is_date_field(
            flt(column="paramP1", control="mskP1", label="Plan Date")))


class DateTargets(unittest.TestCase):
    def test_finds_a_from_to_pair(self):
        info = {"filters": [flt(column="paramFromDate"), flt(column="paramEndDate"),
                            flt(column="paramPo", control="edtPo")]}
        frm, to, singles = core.date_targets(info)
        self.assertEqual(frm["column"], "paramFromDate")
        self.assertEqual(to["column"], "paramEndDate")
        self.assertEqual(singles, [])

    def test_a_screen_with_one_date_reports_it_as_a_single(self):
        # The old rule matched only *fromdate*/*enddate*, so this screen was
        # reported as having no date filter and ran on whatever was in it.
        info = {"filters": [flt(column="planYmd")]}
        frm, to, singles = core.date_targets(info)
        self.assertIsNone(frm)
        self.assertIsNone(to)
        self.assertEqual([s["column"] for s in singles], ["planYmd"])

    def test_a_vendor_code_is_never_the_end_date(self):
        info = {"filters": [flt(column="paramFromDate"),
                            flt(column="paramVendorCode", control="edtVendor",
                                value="10748321")]}
        frm, to, _ = core.date_targets(info)
        self.assertEqual(frm["column"], "paramFromDate")
        self.assertIsNone(to)


class DateWidth(unittest.TestCase):
    def test_full_date_into_an_empty_field(self):
        self.assertEqual(core.fit_date_to_field("20260908", ""), "20260908")

    def test_month_field_gets_six_digits(self):
        # Writing eight digits into a YYYYMM field is accepted and the query
        # then answers something else.
        self.assertEqual(core.fit_date_to_field("20260908", "202608"), "202609")

    def test_year_field_gets_four(self):
        self.assertEqual(core.fit_date_to_field("20260908", "2025"), "2026")

    def test_a_formatted_existing_value_still_counts_as_eight(self):
        self.assertEqual(core.fit_date_to_field("20260908", "2026-08-01"), "20260908")


class NormaliseDate(unittest.TestCase):
    def test_accepts_the_ways_people_type_it(self):
        for raw in ("20260907", "2026-09-07", "2026/09/07", " 2026.09.07 "):
            self.assertEqual(core.normalise_date(raw), "20260907")

    def test_blank_is_none_not_an_error(self):
        self.assertIsNone(core.normalise_date(""))
        self.assertIsNone(core.normalise_date(None))

    def test_rejects_a_date_that_does_not_exist(self):
        with self.assertRaises(ValueError):
            core.normalise_date("20260231")

    def test_rejects_a_partial_date_rather_than_guessing(self):
        with self.assertRaises(ValueError):
            core.normalise_date("2026-09")


class MatchFilter(unittest.TestCase):
    def setUp(self):
        self.info = {
            "filters": [flt(column="paramPo", label="Production Order", control="edtPo"),
                        flt(column="paramFromDate", label="Plan Date", control="mskDateFrom"),
                        flt(column="paramTecoYn", label="TECO", control="cboTeco")],
            "unbound": [flt(column="", label="Lot", control="edtLotNo", bound=False)],
        }

    def test_by_column(self):
        self.assertEqual(core.match_filter(self.info, "paramPo")["control"], "edtPo")

    def test_by_label_case_insensitively(self):
        self.assertEqual(core.match_filter(self.info, "production order")["column"],
                         "paramPo")

    def test_by_control_name(self):
        self.assertEqual(core.match_filter(self.info, "cboTeco")["column"], "paramTecoYn")

    def test_an_unbound_control_is_reachable_by_name(self):
        # A screen that binds none of its filters used to be undriveable.
        found = core.match_filter(self.info, "Lot")
        self.assertEqual(found["control"], "edtLotNo")
        self.assertFalse(found["bound"])

    def test_unknown_name_returns_none(self):
        self.assertIsNone(core.match_filter(self.info, "nothing like this"))

    def test_ambiguous_partial_returns_every_candidate(self):
        info = {"filters": [flt(column="paramFromDate", label="Plan Date"),
                            flt(column="paramEndDate", label="Plan Date To")]}
        found = core.match_filter(info, "date")
        self.assertIsInstance(found, list)
        self.assertEqual(len(found), 2)


class DateColumnNaming(unittest.TestCase):
    """A result column is only reported as a date when it is NAMED like one.
    Live output once listed prodTime (a time), planWeekno (a week number) and
    modelDesc (a model code) as "dates that came back", because all three are
    six or eight digits."""

    def named_like_a_date(self, column):
        return bool(core.words(column) & core._DATE_WORDS)

    def test_real_date_columns(self):
        for column in ("planYmd", "createDate", "workDt", "stdYm"):
            self.assertTrue(self.named_like_a_date(column), column)

    def test_look_alikes_are_not_dates(self):
        for column in ("prodTime", "planWeekno", "modelDesc", "poNo"):
            self.assertFalse(self.named_like_a_date(column), column)

    def test_date_named_columns_offers_real_candidates_before_any_rows_exist(self):
        # This is what the --verify question hint uses before Inquiry has
        # ever run: no row values exist yet to confirm a date SHAPE, only
        # the dataset's own column names - so naming is all there is to go
        # on, and it must still exclude internal (_-prefixed) columns and
        # non-date look-alikes.
        columns = ["planYmd", "prodTime", "_rowType", "createDate", "poNo"]
        self.assertEqual(core.date_named_columns(columns), ["planYmd", "createDate"])


class InquirySettleTracker(unittest.TestCase):
    """The settle-decision core of poll_inquiry(). Two live findings shaped
    this (HISTORY.md Phase 65.2): replaying M4131UM00 with the same
    division right after recording it produced the same correct 10-row
    answer, and a direct trace of the poll loop proved the count did not
    merely fail to differ from the pre-click snapshot - it never changed
    on ANY single poll, 17+ seconds straight, with no other observable
    signal available on that screen. An unconfirmed-but-genuinely-stable
    count must still settle eventually - just with more patience than a
    confirmed one, not a five-minute failure on a result that was correct
    the whole time."""

    SETTLE = 4
    UNCONFIRMED = 12   # InquirySettle's default: settle_checks * 3

    def feed(self, before, polls, settle_checks=None, unconfirmed=None):
        """`before` is the pre-click snapshot; `polls` are the readings fed
        one per poll. Returns the settled count, or None if the sequence
        never settles."""
        tracker = core.InquirySettle(
            before, settle_checks=settle_checks or self.SETTLE,
            unconfirmed_settle_checks=unconfirmed)
        for count in polls:
            settled = tracker.step(count)
            if settled is not None:
                return settled
        return None

    def test_a_confirmed_change_settles_after_settle_checks_matches(self):
        # before=0, count changes to 875 and holds - needs settle_checks+1
        # matching reads (the arrival plus settle_checks repeats).
        self.assertIsNone(self.feed(0, [875] * self.SETTLE))
        self.assertEqual(self.feed(0, [875] * (self.SETTLE + 1)), 875)

    def test_an_unconfirmed_stable_count_still_settles_but_needs_more_reads(self):
        # before=10 - the live-traced case: the count never once differs
        # from `before` or from the previous poll. settle_checks alone is
        # not enough...
        self.assertIsNone(self.feed(10, [10] * (self.SETTLE + 1)))
        # ...but it does settle, given the longer unconfirmed threshold.
        self.assertEqual(self.feed(10, [10] * (self.UNCONFIRMED + 1)), 10)

    def test_a_genuinely_empty_result_settles_with_the_same_patience_as_an_unconfirmed_nonzero_one(self):
        # Live bug (HISTORY.md Phase 71): a date range with genuinely no
        # matching rows burned the full 300s max_wait and then failed,
        # every time, because zero used to be a hard exception that NEVER
        # settled regardless of how long it held. A brief run of stable
        # zeros is still a round trip in progress, not an answer...
        self.assertIsNone(self.feed(0, [0] * (self.SETTLE + 1)))
        # ...but zero is not otherwise special: given the same sustained
        # stability already trusted for an unconfirmed nonzero count, a
        # genuinely empty result must settle too, not hang forever.
        self.assertEqual(self.feed(0, [0] * (self.UNCONFIRMED + 1)), 0)

    def test_a_stale_nonzero_count_dropping_to_zero_is_not_trusted_fast(self):
        # HISTORY.md Phase 82.16, live-caught replaying Q2111UM00: `before`
        # was a stale 175 left over from an earlier query on the same
        # screen. Nexacro clears the dataset to 0 UNCONDITIONALLY the
        # instant Inquiry is clicked - true whether the real answer will be
        # 0 or 175 again - so seeing it drop away from the stale baseline
        # is proof the click registered, never proof the real answer has
        # arrived. Trusting it fast here previously reported "0 rows,
        # confirmed" in ~4 polls while the real answer (also 175) was still
        # in flight; a manual re-click of the identical query moments later
        # returned 175 correctly, proving the data was never the problem.
        # A stable zero must pay the same patience an unconfirmed-but-
        # never-seen-to-move nonzero count already pays, stale baseline or
        # not.
        self.assertIsNone(self.feed(7, [0] * (self.SETTLE + 1)))
        self.assertEqual(self.feed(7, [0] * (self.UNCONFIRMED + 1)), 0)

    def test_a_stale_nonzero_count_changing_to_a_new_nonzero_answer_still_settles_fast(self):
        # The symmetric case Phase 82.16 must NOT break: a stale count
        # actually changing to a DIFFERENT, real, nonzero answer remains
        # confident, fast-settling evidence - only zero itself is untrusted
        # as change evidence, never a genuine nonzero transition.
        self.assertEqual(self.feed(7, [42] * (self.SETTLE + 1)), 42)

    def test_a_count_that_never_stabilizes_never_settles(self):
        # Genuinely erratic - never the same value twice in a row - must
        # not be mistaken for settled just because time passed.
        self.assertIsNone(self.feed(0, list(range(1, 14))))


class TransactionProofDecisionLogic(unittest.TestCase):
    """HISTORY.md Phase 82.6, live-traced rather than guessed at: every
    Inquiry click on P1112UM00 produced one or more `POST .../nexacro.do`
    requests, each answered HTTP 200 with a real response body (519,530
    bytes for a 738-row query). `TransactionProof` is the pure decision
    logic fed these events; the live connection is a separate concern
    (`cdp_common.open_event_listener()`)."""

    def request_event(self, request_id, method="POST", url="http://x/mes4/pm/nexacro.do"):
        return {"method": "Network.requestWillBeSent",
               "params": {"requestId": request_id,
                          "request": {"method": method, "url": url}}}

    def response_event(self, request_id, status=200):
        return {"method": "Network.responseReceived",
               "params": {"requestId": request_id, "response": {"status": status}}}

    def test_unproven_before_any_events(self):
        self.assertFalse(core.TransactionProof().proven)

    def test_a_full_request_response_pair_proves_it(self):
        proof = core.TransactionProof()
        proof.feed([self.request_event("1"), self.response_event("1", 200)])
        self.assertTrue(proof.proven)
        self.assertEqual(proof.confirmed[0]["url"], "http://x/mes4/pm/nexacro.do")

    def test_a_request_with_no_response_yet_is_not_proof(self):
        proof = core.TransactionProof()
        proof.feed([self.request_event("1")])
        self.assertFalse(proof.proven)

    def test_events_can_arrive_across_separate_feed_calls(self):
        # drain_events() is polled repeatedly; the request and its response
        # will usually land in different batches.
        proof = core.TransactionProof()
        proof.feed([self.request_event("1")])
        proof.feed([self.response_event("1", 200)])
        self.assertTrue(proof.proven)

    def test_a_non_2xx_response_does_not_prove_it(self):
        proof = core.TransactionProof()
        proof.feed([self.request_event("1"), self.response_event("1", 500)])
        self.assertFalse(proof.proven)

    def test_a_get_request_to_the_same_url_does_not_count(self):
        # Nexacro's own transaction endpoint is always POSTed to; a GET
        # (a static asset, a redirect target) is not the same evidence.
        proof = core.TransactionProof()
        proof.feed([self.request_event("1", method="GET"), self.response_event("1", 200)])
        self.assertFalse(proof.proven)

    def test_an_unrelated_url_does_not_count(self):
        proof = core.TransactionProof()
        proof.feed([self.request_event("1", url="http://x/some/other/endpoint"),
                   self.response_event("1", 200)])
        self.assertFalse(proof.proven)

    def test_a_response_for_an_untracked_request_id_is_ignored_not_a_crash(self):
        proof = core.TransactionProof()
        proof.feed([self.response_event("never-requested", 200)])
        self.assertFalse(proof.proven)

    def test_multiple_confirmed_requests_all_accumulate(self):
        # Live-observed: one Inquiry click produced two - sm/nexacro.do
        # (9,000 bytes) and pm/nexacro.do (519,530 bytes).
        proof = core.TransactionProof()
        proof.feed([self.request_event("1", url="http://x/mes4/sm/nexacro.do"),
                   self.request_event("2", url="http://x/mes4/pm/nexacro.do"),
                   self.response_event("1", 200), self.response_event("2", 200)])
        self.assertTrue(proof.proven)
        self.assertEqual(len(proof.confirmed), 2)


class WatchNexacroTransactionLiveGlue(unittest.TestCase):
    """The live-connection half of Phase 82.6: opens a listener dedicated
    to events (never the connection also used for evaluate() calls - see
    cdp_common.open_event_listener()'s own docstring), polls it, and
    returns whatever TransactionProof concluded - never fatal on its own,
    since this is supplementary evidence, not the primary proof a caller
    depends on."""

    def test_returns_proven_as_soon_as_evidence_arrives(self):
        listener = Mock()
        events_by_call = iter([
            [],
            [{"method": "Network.requestWillBeSent",
             "params": {"requestId": "1",
                       "request": {"method": "POST", "url": "http://x/mes4/pm/nexacro.do"}}}],
            [{"method": "Network.responseReceived",
             "params": {"requestId": "1", "response": {"status": 200}}}],
        ])
        clock = _FakeClock()
        with patch.object(core.cdp_common, "open_event_listener", return_value=listener), \
             patch.object(core.cdp_common, "drain_events",
                          side_effect=lambda _l: next(events_by_call, [])), \
             patch.object(core, "time", clock):
            proof = core.watch_nexacro_transaction("ws://x", max_wait=30, poll_interval=1)
        self.assertTrue(proof.proven)
        listener.close.assert_called_once()

    def test_a_listener_that_cannot_be_opened_returns_unproven_not_a_crash(self):
        with patch.object(core.cdp_common, "open_event_listener",
                          side_effect=RuntimeError("Network domain refused")):
            proof = core.watch_nexacro_transaction("ws://x", max_wait=1)
        self.assertFalse(proof.proven)

    def test_gives_up_at_the_deadline_when_nothing_ever_arrives(self):
        listener = Mock()
        clock = _FakeClock()
        with patch.object(core.cdp_common, "open_event_listener", return_value=listener), \
             patch.object(core.cdp_common, "drain_events", return_value=[]), \
             patch.object(core, "time", clock):
            proof = core.watch_nexacro_transaction("ws://x", max_wait=5, poll_interval=1)
        self.assertFalse(proof.proven)
        listener.close.assert_called_once()


class ChooseGrid(unittest.TestCase):
    def test_the_only_grid_wins(self):
        info = {"grids": [grid("grdMain", "dsMasterProdPlan", 400000)]}
        chosen, rivals = core.choose_grid(info)
        self.assertEqual(chosen["dataset"], "dsMasterProdPlan")
        self.assertEqual(rivals, [])

    def test_a_hidden_grid_is_not_chosen_over_a_visible_one(self):
        info = {"grids": [grid("grdHidden", "dsOther", 900000, visible=False),
                          grid("grdMain", "dsMain", 400000)]}
        chosen, _ = core.choose_grid(info)
        self.assertEqual(chosen["name"], "grdMain")

    def test_a_comparable_second_grid_is_reported_not_hidden(self):
        # Master-detail screens have two. Picking the larger silently is a
        # coin toss, and the wrong side of it exports the wrong data.
        info = {"grids": [grid("grdMaster", "dsMaster", 400000),
                          grid("grdDetail", "dsDetail", 380000)]}
        chosen, rivals = core.choose_grid(info)
        self.assertEqual(chosen["name"], "grdMaster")
        self.assertEqual([r["name"] for r in rivals], ["grdDetail"])

    def test_many_grids_on_one_dataset_are_not_rivals(self):
        # HISTORY.md Phase 82.22, P3131UM00: nine grids on one dataset (tab
        # variants of the same rows) made the run refuse with "more than one
        # plausible result grid", naming seven copies of the same data.
        info = {"grids": [grid(f"grdDetail{n}", "dsShared", 400000) for n in range(1, 8)]}
        best, rivals = core.choose_grid(info)
        self.assertIsNotNone(best)
        self.assertEqual(rivals, [])

    def test_a_grid_on_a_different_dataset_is_still_a_rival_among_shared_ones(self):
        info = {"grids": [grid("grdA1", "dsShared", 400000),
                          grid("grdA2", "dsShared", 390000),
                          grid("grdOther", "dsOther", 380000)]}
        best, rivals = core.choose_grid(info)
        self.assertEqual([g["name"] for g in rivals], ["grdOther"])

    def test_a_small_second_grid_is_not_an_ambiguity(self):
        info = {"grids": [grid("grdMaster", "dsMaster", 400000),
                          grid("grdTiny", "dsTiny", 9000)]}
        _, rivals = core.choose_grid(info)
        self.assertEqual(rivals, [])

    def test_prefer_by_dataset_name_settles_it(self):
        info = {"grids": [grid("grdMaster", "dsMaster", 400000),
                          grid("grdDetail", "dsDetail", 380000)]}
        chosen, rivals = core.choose_grid(info, prefer="dsDetail")
        self.assertEqual(chosen["name"], "grdDetail")
        self.assertEqual(rivals, [])

    def test_an_unmatched_preference_does_not_fall_back_silently(self):
        info = {"grids": [grid("grdMaster", "dsMaster", 400000)]}
        chosen, rivals = core.choose_grid(info, prefer="dsNoSuchThing")
        self.assertIsNone(chosen)
        self.assertTrue(rivals)

    def test_no_grids_at_all(self):
        self.assertEqual(core.choose_grid({"grids": []}), (None, []))


class Names(unittest.TestCase):
    def test_a_report_title_with_a_slash_becomes_a_usable_file_name(self):
        self.assertEqual(core.safe_name("Production Plan by Order(Line)"),
                         "Production Plan by Order(Line)")
        self.assertNotIn("/", core.safe_name("Plan / Actual"))
        self.assertNotIn(":", core.safe_name("Shift: A"))

    def test_an_empty_title_still_yields_a_name(self):
        self.assertEqual(core.safe_name("   "), "report")

    def test_windows_reserved_device_names_are_not_used_bare(self):
        # Windows blocks CON, PRN, AUX, NUL, COM1-9, LPT1-9 EXACTLY,
        # regardless of extension - a report titled exactly one of these
        # is not implausible across 810 screens.
        for reserved in ("CON", "con", "PRN", "AUX", "NUL", "COM1", "LPT9"):
            name = core.safe_name(reserved)
            self.assertNotEqual(name.upper(), reserved.upper())

    def test_a_trailing_dot_or_space_is_stripped(self):
        # Windows silently drops a trailing dot/space from a filename too.
        self.assertEqual(core.safe_name("Report."), "Report")
        self.assertEqual(core.safe_name("Report "), "Report")


class Digits(unittest.TestCase):
    def test_a_formatted_date_and_a_raw_one_compare_equal(self):
        self.assertEqual(core.digits_only("2026-09-08"), core.digits_only("20260908"))


class IsPureNumber(unittest.TestCase):
    """`verify_rows()` and `apply()`'s did-it-take check both used to decide
    "compare by digits alone" on nothing more than "the text contains a
    digit somewhere" - which made digits_only("MODEL-A1") ==
    digits_only("MODEL-B1") (both "1") report a wrong value as verified,
    and a filter that silently landed as the wrong code as having "taken"
    correctly. Only a value that is ENTIRELY digits and separators may be
    reduced to its digits."""

    def test_dates_and_plain_numbers_are_pure(self):
        for text in ("20260908", "2026-09-08", "2026/09/08", "12:30", "011074232146"):
            self.assertTrue(core.is_pure_number(text), text)

    def test_an_alphanumeric_code_is_not_pure_even_with_a_digit_in_it(self):
        for text in ("MODEL-A1", "MODEL-B1", "SM-A137F", "P1112UM00"):
            self.assertFalse(core.is_pure_number(text), text)

    def test_the_exact_collision_that_was_silently_accepted(self):
        # digits_only alone cannot tell these apart - is_pure_number must
        # keep them off that path entirely.
        self.assertEqual(core.digits_only("MODEL-A1"), core.digits_only("MODEL-B1"))
        self.assertFalse(core.is_pure_number("MODEL-A1"))
        self.assertFalse(core.is_pure_number("MODEL-B1"))

    def test_verify_rows_rejects_a_different_alphanumeric_value(self):
        result = {"found": True, "columns": ["modelCode"],
                  "rows": [{"modelCode": "MODEL-B1"}]}
        with patch.object(core, "read_rows", return_value=result):
            seen, problem = core.verify_rows(None, "F", "DS", "modelCode", "MODEL-A1")
        self.assertIsNotNone(problem)
        self.assertIn("MODEL-A1", problem)


class ValuesMatch(unittest.TestCase):
    """values_match() is the shared comparison for verify_rows(), apply()
    and type_text(). Checking only ONE side's shape was not enough, and
    this project shipped that mistake twice: is_pure_number(expected)
    alone let MODEL-B1 verify against an expected MODEL-A1, and checking
    only the WANTED side the other way let a wanted "123" silently accept
    an actual "X123" - confirmed live, verify_rows(..., "123") against a
    row holding "X123" returned problem=None before this fix."""

    def test_both_sides_must_be_numbers_to_compare_as_digits(self):
        self.assertTrue(core.values_match("2026-09-08", "20260908"))
        self.assertFalse(core.values_match("MODEL-A1", "MODEL-B1"))

    def test_a_pure_wanted_value_does_not_silently_accept_an_alphanumeric_actual(self):
        # The exact live-reproduced mirror bug: "123" alone looks like a
        # number worth reducing to digits, but "X123" does not - so they
        # must NOT be compared as digits.
        self.assertFalse(core.values_match("123", "X123"))
        self.assertFalse(core.values_match("X123", "123"))

    def test_a_decimal_point_is_not_a_date_separator(self):
        # Live-confirmed: digits_only("1.2") == digits_only("12") == "12",
        # so a quantity field's decimal value could pass verification
        # against a completely different whole number.
        self.assertFalse(core.values_match("1.2", "12"))
        self.assertTrue(core.values_match("1.2", "1.2"))

    def test_a_leading_sign_is_not_a_date_separator(self):
        # Live-confirmed: digits_only("-1") == digits_only("1") == "1",
        # so a negative adjustment could pass verification against its own
        # positive value.
        self.assertFalse(core.values_match("-1", "1"))
        self.assertTrue(core.values_match("-1", "-1"))
        # A mid-string "-" is still a real date separator.
        self.assertTrue(core.values_match("2026-09-08", "20260908"))

    def test_exact_text_still_matches_case_insensitively(self):
        self.assertTrue(core.values_match("ABC", "abc"))
        self.assertFalse(core.values_match("ABC", "XYZ"))


class ClearStaleFailure(unittest.TestCase):
    """A leftover filter from an earlier run that REFUSES to clear used to
    be silently swallowed (`except RuntimeError: pass`) - the exact failure
    class this method exists to prevent, just one level down: instead of an
    old value never being asked to leave, it is a value that refused to
    leave when asked, and the run carried on anyway."""

    def make_screen(self, filter_value="Old PO", apply_raises=True):
        info = {
            "filters": [flt(column="poNo", control="edtPo", value=filter_value,
                            label="Production Order")],
            "unbound": [],
        }
        screen = core.Screen(ws=None, code="P1112UM00",
                             opened={"menuId": "M", "winId": "W"}, info=info)
        if apply_raises:
            screen.apply = lambda f, v: (_ for _ in ()).throw(
                RuntimeError("did not take"))
        else:
            screen.apply = lambda f, v: ""
        return screen

    def test_a_filter_that_refuses_to_clear_stops_the_run(self):
        screen = self.make_screen(apply_raises=True)
        with self.assertRaisesRegex(RuntimeError, "Old PO"):
            screen.clear_stale()

    def test_a_filter_that_clears_successfully_is_reported_not_raised(self):
        screen = self.make_screen(apply_raises=False)
        cleared = screen.clear_stale()
        self.assertEqual(cleared, ["Production Order=Old PO"])


class SetOptionDisabled(unittest.TestCase):
    """Live finding (HISTORY.md Phase 71.2): a left-panel BUTTON option's
    CSS class (`_Dis`/`_Default`) names its DESELECTED visual style, not
    whether it can be clicked - a real Korean-labeled option on P1112UM00
    ('실적일') showed as ordinary "not selected", but a click sent to its
    exact live coordinates changed nothing at all, because Nexacro's own
    `enable` flag was false the whole time (a screen-state precondition
    unrelated to the CSS class). set_option() must refuse BEFORE clicking
    a disabled option, not click it and then report the same generic
    "could not prove selected" a real detection bug would also produce."""

    def make_screen(self, options):
        screen = core.Screen(ws=None, code="P1112UM00",
                             opened={"menuId": "M", "winId": "W"}, info={})
        self.patcher = patch.object(core, "left_options",
                                    return_value={"options": options})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.click_patcher = patch.object(core, "click_element_by_rect")
        self.click = self.click_patcher.start()
        self.addCleanup(self.click_patcher.stop)
        return screen

    def opt(self, label, state="not selected", enabled=True, kind="button",
            name=None):
        return {"label": label, "id": "x", "name": name or label, "path": "",
                "cls": "", "state": state,
                "kind": kind, "enabled": enabled, "x": 1, "y": 1}

    def test_a_disabled_option_is_refused_before_any_click(self):
        screen = self.make_screen([self.opt("실적일", enabled=False)])
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            screen.set_option("실적일")
        self.click.assert_not_called()

    def test_an_enabled_option_missing_from_state_is_still_clickable(self):
        # Options discovered before this fix carry no "enabled" key at
        # all - .get("enabled", True) must default to clickable, not
        # silently refuse every option on an older code path.
        opt = self.opt("PLANT")
        del opt["enabled"]
        screen = self.make_screen([opt])
        discover_patcher = patch.object(core, "discover", return_value={})
        discover_patcher.start()
        self.addCleanup(discover_patcher.stop)
        with self.assertRaises(RuntimeError) as cm:
            # Still fails (the mocked left_options() never reports it
            # selected afterwards), but it must reach the click first -
            # proven both by the click being called and by the failure
            # NOT being the "disabled" refusal.
            screen.set_option("PLANT", verify_wait=0)
        self.assertNotIn("disabled", str(cm.exception))
        self.click.assert_called_once()

    def test_the_click_is_confirmed_by_name_even_if_the_label_changes(self):
        # The click can rebuild the left panel, and a rebuilt panel is exactly
        # where a label could come back rendered differently. Confirming by
        # label would then fail to find a control that WAS successfully
        # selected, and report "could not prove selected" for a click that
        # worked (HISTORY.md Phase 76.3).
        before = self.opt("Create Date", name="btnCreate")
        after = self.opt("생성일", name="btnCreate", state="selected")
        screen = core.Screen(ws=None, code="P1112UM00",
                             opened={"menuId": "M", "winId": "W"}, info={})
        panels = iter([{"options": [before]}, {"options": [after]}])
        with patch.object(core, "left_options",
                          side_effect=lambda _ws: next(panels, {"options": [after]})), \
             patch.object(core, "click_element_by_rect"), \
             patch.object(core, "discover", return_value={}), \
             patch.object(core.time, "sleep"):
            result = screen.set_option("Create Date", verify_wait=5)
        self.assertEqual(result["name"], "btnCreate")
        self.assertIn("selected", result["outcome"])


#: The real left panel of P1112UM00, read live from the running screen on
#: 2026-09-16 while G-MES rendered Korean. Every `name` here is the control's
#: own Nexacro name, and every label is what that control displayed. This is
#: the fixture the whole phase turns on, so it is real data rather than
#: invented data: the point being proved is that `생성일` and `btnCreate` are
#: the same control, and only the live screen can say that.
LIVE_P1112UM00_OPTIONS = [
    ("조회", "btnSearch"),
    ("Org", "tabTitle_Org"),
    ("Prod", "tabTitle_Prod"),
    ("Fac", "tabTitle_Fac"),
    ("Proc", "tabTitle_Proc"),
    ("STD", "btnstd"),
    ("PLANT", "btnplant"),
    ("과거 조직도 포함", "chkDisuseYn"),
    ("실적일", "btnProduce"),
    ("계획일", "btnPlan"),
    ("생성일", "btnCreate"),
    ("DB 조회", "chkPoSearch"),
    ("일반 검색", "btnSearchNormal"),
    ("비교 검색", "btnSearchCompare"),
    ("OI", "btnOI"),
]

#: The same panel as it renders in English, for the reverse direction. Labels
#: from GMES_SKILL.md #32, names unchanged - which is the property under test.
ENGLISH_P1112UM00_OPTIONS = [
    ("Inquiry", "btnSearch"),
    ("Org", "tabTitle_Org"),
    ("Prod", "tabTitle_Prod"),
    ("Fac", "tabTitle_Fac"),
    ("Proc", "tabTitle_Proc"),
    ("STD", "btnstd"),
    ("PLANT", "btnplant"),
    ("Including Past Org.", "chkDisuseYn"),
    ("Actual Date", "btnProduce"),
    ("Plan Date", "btnPlan"),
    ("Create Date", "btnCreate"),
    ("DB Search", "chkPoSearch"),
    ("General", "btnSearchNormal"),
    ("Compare", "btnSearchCompare"),
    ("OI", "btnOI"),
]


def panel(pairs, selected=()):
    """A left_options() result from (label, name) pairs."""
    return [{"label": label, "name": name, "id": f"win_0_1.form.{name}",
             "path": f"form.divLeft.form.{name}", "cls": "", "kind": "button",
             "state": "selected" if name in selected else "not selected",
             "enabled": True, "x": 1, "y": 1}
            for label, name in pairs]


class OptionKeys(unittest.TestCase):
    """The semantic key is the component name with the Nexacro control-type
    prefix removed. Names are authored in the screen's XFDL, so they are the
    one part of a left-panel option that does not change with the UI
    language (HISTORY.md Phase 76)."""

    def test_the_real_control_names_normalise_as_expected(self):
        for name, expected in (("btnCreate", "create"), ("btnPlan", "plan"),
                               ("btnProduce", "produce"), ("btnstd", "std"),
                               ("btnplant", "plant"), ("chkDisuseYn", "disuseyn"),
                               ("chkPoSearch", "posearch"), ("btnOI", "oi"),
                               ("btnSearchNormal", "searchnormal")):
            with self.subTest(name=name):
                self.assertEqual(core.option_key(name), expected)

    def test_tabtitle_is_stripped_before_the_shorter_tab_prefix(self):
        # Stripping "tab" first would leave "title_org".
        self.assertEqual(core.option_key("tabTitle_Org"), "org")
        self.assertEqual(core.option_key("tabTitle_Proc"), "proc")

    def test_keys_are_unique_across_the_real_panel(self):
        # If two options shared a key the resolver would report ambiguity and
        # refuse, which is safe but useless - so this is worth knowing.
        keys = [core.option_key(n) for _l, n in LIVE_P1112UM00_OPTIONS]
        self.assertEqual(len(keys), len(set(keys)), keys)

    def test_a_missing_or_odd_name_does_not_raise(self):
        for value in (None, "", "   ", "btn", "___"):
            with self.subTest(value=value):
                self.assertIsInstance(core.option_key(value), str)

    def test_the_generated_js_actually_reports_the_stable_identity(self):
        # The JS cannot be executed offline, so this pins its SOURCE. Without
        # `name` and `path` coming back from the browser there is no
        # language-independent identity to store and the whole phase is
        # decorative - and every offline test would still pass, because they
        # all build their panels from fixtures.
        js = core.JS_LEFT_OPTIONS
        self.assertIn("name: name", js)
        self.assertIn("path: relativePath(id)", js)
        self.assertIn("obj.name", js)
        # The window segment must be stripped, or the path embeds an instance
        # number that changes on every open (GMES_SKILL.md #7).
        self.assertIn("relativePath", js)
        self.assertIn("win", js)

    def test_the_relative_path_strips_a_renumbered_window_segment(self):
        # The regex in JS_LEFT_OPTIONS, mirrored here so its INTENT is tested:
        # a real id from the live screen must lose everything up to and
        # including winPPM0219_0_926.
        live = ("mainframe.vFrameSet1.vFrameSet2.hFrameSet1.workFrameSet."
                "winPPM0219_0_926.form.divLeft.form.divLeftSub.form.divFilter."
                "form.divWidgetMain.form.divWidgetFilterPPM0222.form.divBasic."
                "form.btnCreate")
        parts = live.split(".")
        index = next(i for i, p in enumerate(parts)
                     if re.match(r"^win.*_\d+_\d+$", p))
        relative = ".".join(parts[index + 1:])
        self.assertTrue(relative.startswith("form.divLeft"))
        self.assertTrue(relative.endswith("btnCreate"))
        self.assertNotIn("winPPM0219", relative)


class ReplayAcrossLanguages(unittest.TestCase):
    """The reported failure, reproduced exactly.

    P1112UM00 was recorded with the option "Create Date" while G-MES rendered
    English. The same screen now renders Korean, where that control reads
    `생성일`, and replay stopped with "no left-panel option called 'Create
    Date'. Available: 조회, Org, Prod, ...". The control was there the whole
    time, and is still named `btnCreate`."""

    KOREAN = panel(LIVE_P1112UM00_OPTIONS)
    ENGLISH = panel(ENGLISH_P1112UM00_OPTIONS)

    def test_the_exact_reported_failure_now_resolves(self):
        option, how = core.resolve_option(self.KOREAN, "Create Date")
        self.assertEqual(option["name"], "btnCreate")
        self.assertEqual(option["label"], "생성일")
        self.assertEqual(how, "english alias")

    def test_a_migrated_profile_replays_on_the_korean_screen(self):
        # The pre-Phase-76 profile shape, verbatim: a bare English label.
        option, _how = core.resolve_option(self.KOREAN, "Create Date")
        identity = core.option_identity(option)
        self.assertEqual(identity["key"], "create")
        # ...and once healed, it resolves by identity, with no reliance on
        # language at all - in EITHER rendering.
        for rendering, expected in ((self.KOREAN, "생성일"),
                                    (self.ENGLISH, "Create Date")):
            with self.subTest(label=expected):
                again, how = core.resolve_option(rendering, identity)
                self.assertEqual(again["name"], "btnCreate")
                self.assertEqual(again["label"], expected)
                self.assertEqual(how, "component name")

    def test_a_profile_recorded_in_korean_replays_in_english(self):
        # The reverse direction matters just as much: whoever records next
        # will record Korean labels, and English must not then break.
        recorded = core.option_identity(
            core.resolve_option(self.KOREAN, "생성일")[0])
        option, how = core.resolve_option(self.ENGLISH, recorded)
        self.assertEqual(option["label"], "Create Date")
        self.assertEqual(how, "component name")

    def test_every_english_label_resolves_on_the_korean_panel_or_refuses(self):
        # Blanket sweep. Each English label must either find its own control
        # or fail - never resolve to a DIFFERENT control, which is the only
        # outcome that could silently change what a report means.
        for label, name in ENGLISH_P1112UM00_OPTIONS:
            with self.subTest(label=label):
                try:
                    option, _how = core.resolve_option(self.KOREAN, label)
                except RuntimeError:
                    continue            # refused; safe
                self.assertEqual(
                    option["name"], name,
                    f"{label!r} resolved to {option['name']} instead of {name}")

    def test_the_identity_survives_a_renumbered_window(self):
        # Window ids are renumbered on every open (GMES_SKILL.md #7), so the
        # identity must not contain one.
        recorded = core.option_identity(
            core.resolve_option(self.KOREAN, "생성일")[0])
        moved = [dict(o, id=o["id"].replace("win_0_1", "winPPM0219_0_926"))
                 for o in self.KOREAN]
        option, _how = core.resolve_option(moved, recorded)
        self.assertEqual(option["name"], "btnCreate")


class OptionResolutionSafety(unittest.TestCase):
    """Never guess between several matches, and never resolve to the wrong
    control (CLAUDE.md 3.9)."""

    KOREAN = panel(LIVE_P1112UM00_OPTIONS)

    def test_plan_and_plant_are_never_confused(self):
        # A prefix rule would match "PLANT" against btnPlan as well. Both of
        # these exist on the real screen and mean entirely different things.
        self.assertEqual(
            core.resolve_option(self.KOREAN, "PLANT")[0]["name"], "btnplant")
        self.assertEqual(
            core.resolve_option(self.KOREAN, "Plan Date")[0]["name"], "btnPlan")

    def test_including_past_org_does_not_resolve_to_the_org_tab(self):
        # The rejected "key appears anywhere in the request" rule matched the
        # word "org" in "Including Past Org." and picked the Org CATEGORY TAB -
        # a confidently wrong match that silently changes the query. Refusing
        # is the correct outcome here.
        with self.assertRaises(RuntimeError) as cm:
            core.resolve_option(self.KOREAN, "Including Past Org.")
        self.assertNotIn("tabTitle_Org", str(cm.exception).split("offers")[0])

    def test_two_controls_sharing_a_key_are_refused_not_guessed(self):
        ambiguous = panel([("생성일", "btnCreate"), ("Created", "btnCreate")])
        with self.assertRaisesRegex(RuntimeError, "Refusing to guess"):
            core.resolve_option(ambiguous, "Create Date")

    def test_the_failure_message_lists_every_key_to_use_instead(self):
        with self.assertRaises(RuntimeError) as cm:
            core.resolve_option(self.KOREAN, "No Such Option")
        message = str(cm.exception)
        self.assertIn("[create]", message)
        self.assertIn("[plant]", message)
        self.assertIn("language-independent", message)

    def test_an_empty_panel_refuses_rather_than_crashing(self):
        with self.assertRaises(RuntimeError):
            core.resolve_option([], "Create Date")
        with self.assertRaises(RuntimeError):
            core.resolve_option([], {"key": "create", "name": "btnCreate"})

    def test_a_vanished_control_is_reported_not_silently_skipped(self):
        # The screen changed and the remembered control is simply gone.
        without = panel([p for p in LIVE_P1112UM00_OPTIONS if p[1] != "btnCreate"])
        with self.assertRaises(RuntimeError) as cm:
            core.resolve_option(without, {"key": "create", "name": "btnCreate",
                                          "path": "", "label": "생성일"})
        self.assertIn("no left-panel option matching", str(cm.exception))

    def test_the_key_resolves_even_when_the_name_was_renamed(self):
        # Identity is tried name -> path -> key, so a control renamed between
        # Nexacro versions still resolves by its normalised key.
        renamed = panel([("생성일", "btnCreateDate")])
        option, how = core.resolve_option(
            renamed, {"key": "createdate", "name": "btnCreate", "path": "",
                      "label": "Create Date"})
        self.assertEqual(option["name"], "btnCreateDate")
        self.assertEqual(how, "semantic key")

    def test_a_korean_label_still_works_as_a_direct_request(self):
        # Someone reading the screen types what they see.
        option, how = core.resolve_option(self.KOREAN, "생성일")
        self.assertEqual(option["name"], "btnCreate")
        self.assertEqual(how, "label")

    def test_the_semantic_key_can_be_passed_directly(self):
        option, how = core.resolve_option(self.KOREAN, "create")
        self.assertEqual(option["name"], "btnCreate")
        self.assertEqual(how, "semantic key")


class OptionProfileEntries(unittest.TestCase):
    """What a profile stores, and what it accepts back."""

    def test_an_identity_keeps_the_label_as_display_metadata_only(self):
        identity = core.option_identity(
            {"name": "btnCreate", "path": "form.x.btnCreate", "label": "생성일"})
        self.assertEqual(identity, {"key": "create", "name": "btnCreate",
                                    "path": "form.x.btnCreate", "label": "생성일"})

    def test_a_dict_entry_round_trips_through_the_profile(self):
        import gmes_profile
        entry = gmes_profile._option_entry(
            {"key": "create", "name": "btnCreate", "path": "p", "label": "생성일"})
        self.assertEqual(entry["name"], "btnCreate")
        self.assertEqual(entry["key"], "create")

    def test_a_bare_string_is_still_accepted_and_kept(self):
        # Every profile written before Phase 76 holds exactly this.
        import gmes_profile
        self.assertEqual(gmes_profile._option_entry("Create Date"), "Create Date")

    def test_an_entry_with_no_identity_degrades_to_its_label(self):
        # Storing {"key": "", "name": ""} would look like an identity and
        # resolve to nothing; a label at least migrates.
        import gmes_profile
        self.assertEqual(
            gmes_profile._option_entry({"key": "", "name": "", "label": "Create Date"}),
            "Create Date")

    def test_display_handles_both_shapes(self):
        self.assertEqual(core.option_display("Create Date"), "Create Date")
        self.assertIn("create", core.option_display(
            {"key": "create", "label": "생성일"}))
        self.assertEqual(core.option_display({"key": "create"}), "create")



class RedactSensitiveColumns(unittest.TestCase):
    """CLAUDE.md 2.3: a G-MES dataset can carry `tokenId`/`refreshTokenId` -
    full session JWTs - in an ordinary-looking form. Console/log output was
    already redacted (gmes_log.py's own _SECRET regex); CSV export was not,
    until this fix."""

    def test_credential_shaped_columns_are_withheld(self):
        cols = ["poNo", "tokenId", "refreshTokenId", "Authorization",
                "planYmd", "cookie_session", "_rowType"]
        safe, dropped = gmes_data.redact_sensitive_columns(cols)
        self.assertEqual(safe, ["poNo", "planYmd"])
        self.assertEqual(set(dropped),
                         {"tokenId", "refreshTokenId", "Authorization", "cookie_session"})

    def test_the_word_does_not_have_to_be_at_the_start(self):
        # refreshTokenId is CLAUDE.md 2.3's own named example, and the word
        # "Token" sits in the MIDDLE of it, not the start - a first version
        # of this filter used re.match(), which only ever anchors at
        # position 0 regardless of the pattern, and missed it.
        safe, dropped = gmes_data.redact_sensitive_columns(["refreshTokenId"])
        self.assertEqual(safe, [])
        self.assertEqual(dropped, ["refreshTokenId"])

    def test_ordinary_columns_are_untouched(self):
        cols = ["poNo", "modelCode", "planYmd", "qty"]
        safe, dropped = gmes_data.redact_sensitive_columns(cols)
        self.assertEqual(safe, cols)
        self.assertEqual(dropped, [])

    def test_verify_rows_rejects_a_pure_expected_value_against_an_alphanumeric_row(self):
        result = {"found": True, "columns": ["poNo"], "rows": [{"poNo": "X123"}]}
        with patch.object(core, "read_rows", return_value=result):
            seen, problem = core.verify_rows(None, "F", "DS", "poNo", "123")
        self.assertIsNotNone(problem)
        self.assertIn("123", problem)


class ScreenCodeShape(unittest.TestCase):
    """open_screen() reuses an already-open tab only for a full screen code or
    menu id. A partial one would match several open screens and pick whichever
    came first; a name has to go through the catalogue, which validates it."""

    PATTERN = r"[A-Za-z]{1,4}\d{4,}[A-Za-z0-9]*"

    def looks_like_a_code(self, text):
        import re
        return bool(re.fullmatch(self.PATTERN, text))

    def test_real_codes_are_recognised(self):
        for code in ("P1112UM00", "P1112WM00", "Q2241UM00", "PPM0219"):
            self.assertTrue(self.looks_like_a_code(code), code)

    def test_a_partial_code_is_not(self):
        self.assertFalse(self.looks_like_a_code("P111"))

    def test_a_screen_name_is_not(self):
        for name in ("Work Calendar", "production plan", "Master Prod. Plan"):
            self.assertFalse(self.looks_like_a_code(name), name)


class GridRebinding(unittest.TestCase):
    """HISTORY.md Phase 82.18, live-caught on R5216UM00 (Mounter Drop
    Analysis): its result grid `grdDetail` is bound to `dsMntDetailListTemp`
    - a 1-column placeholder that never holds a row - until a query answers,
    then re-bound by the screen's own code to `dsMntDetailList`. Discovery
    ran first, so the run polled a dataset that could never fill and
    reported "the query returned no rows" for a screen showing 259. It also
    made a saved profile depend on whether the window happened to be open
    already: cold and warm windows show different dataset names for the same
    screen."""

    def setUp(self):
        import gmes_profile
        self.p = gmes_profile
        f = [flt(column="fromDate", control="mskFrom")]
        self.cold = {"filters": f, "unbound": [],
                     "grids": [grid("grdDetail", "dsMntDetailListTemp", 300000)]}
        self.warm = {"filters": f, "unbound": [],
                     "grids": [grid("grdDetail", "dsMntDetailList", 300000)]}
        self.aliases = {"dsMntDetailList": "dsMntDetailListTemp"}

    # -- the fingerprint ----------------------------------------------------

    def test_without_an_alias_a_cold_and_a_warm_window_look_like_different_screens(self):
        # This is the failure being fixed, kept as a fact about the
        # un-aliased digest so the next two tests mean something.
        self.assertNotEqual(self.p.fingerprint(self.cold), self.p.fingerprint(self.warm))

    def test_with_the_alias_both_windows_hash_to_the_same_screen(self):
        self.assertEqual(self.p.fingerprint(self.cold, self.aliases),
                         self.p.fingerprint(self.warm, self.aliases))

    def test_no_alias_leaves_every_existing_profiles_digest_unchanged(self):
        # The 12 profiles already saved carry no aliases; none may be
        # invalidated by this change.
        self.assertEqual(self.p.fingerprint(self.cold), self.p.fingerprint(self.cold, None))
        self.assertEqual(self.p.fingerprint(self.cold), self.p.fingerprint(self.cold, {}))

    # -- replay -------------------------------------------------------------

    def profile_recorded_cold(self):
        return {"grid": self.p.grid_ref(self.cold["grids"][0]),
                "grid_aliases": self.aliases,
                "fingerprint": self.p.fingerprint(self.cold, self.aliases)}

    def test_a_profile_recorded_cold_replays_in_a_warm_window(self):
        self.assertEqual(self.p.describe_change(self.profile_recorded_cold(), self.warm), [])

    def test_a_profile_recorded_cold_replays_in_a_cold_window(self):
        self.assertEqual(self.p.describe_change(self.profile_recorded_cold(), self.cold), [])

    def test_a_stored_grid_name_that_is_the_rebound_one_still_matches_a_cold_window(self):
        # A profile first written from a warm window holds the re-bound name
        # as its grid. Once the alias is known the cold window's placeholder
        # name must count as the same grid, in this direction too.
        profile = self.profile_recorded_cold()
        profile["grid"] = dict(profile["grid"], dataset="dsMntDetailList")
        self.assertEqual(self.p.describe_change(profile, self.cold), [])

    def test_a_different_grid_is_still_reported_as_gone(self):
        # The alias widens what counts as the SAME grid; it must not make
        # an unrelated one acceptable.
        other = dict(self.cold, grids=[grid("grdDetail", "dsSomethingElse", 300000)])
        problems = self.p.describe_change(self.profile_recorded_cold(), other)
        self.assertTrue(any("is gone" in x for x in problems))

    def test_the_remembered_grid_is_found_under_whichever_name_is_showing(self):
        profile = self.profile_recorded_cold()
        self.assertEqual(self.p.resolve_grid_dataset(profile, self.cold), "dsMntDetailListTemp")
        self.assertEqual(self.p.resolve_grid_dataset(profile, self.warm), "dsMntDetailList")

    def test_with_no_alias_the_remembered_name_is_returned_even_when_absent(self):
        # Preserves today's behaviour: the caller's own "which grid?" error
        # is what says the grid is gone.
        profile = {"grid": self.p.grid_ref(self.cold["grids"][0])}
        self.assertEqual(self.p.resolve_grid_dataset(profile, self.warm), "dsMntDetailListTemp")

    def test_a_profile_with_no_grid_resolves_to_none(self):
        self.assertIsNone(self.p.resolve_grid_dataset({}, self.cold))
        self.assertIsNone(self.p.resolve_grid_dataset(None, self.cold))

    # -- saving -------------------------------------------------------------

    def _save(self, tmp, info, grid_entry, grid_aliases=None):
        with patch.object(self.p, "SCREENS_DIR", tmp):
            self.p.save("R5216UM00", "t", "FFM0826", info, grid=grid_entry, rows=5,
                        grid_aliases=grid_aliases)
            return self.p.load("R5216UM00")

    def test_a_save_remembers_the_alias_and_the_name_seen_when_first_read(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            saved = self._save(tmp, self.cold, self.cold["grids"][0], self.aliases)
        self.assertEqual(saved["grid_aliases"], self.aliases)
        self.assertEqual(saved["grid"]["dataset"], "dsMntDetailListTemp")

    def test_a_warm_run_saves_the_grid_under_its_original_name(self):
        # A replay in an already-warm window sees only the re-bound name and
        # is saved with it as its grid - it must not overwrite the profile's
        # cold-window name and re-break the next cold replay.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._save(tmp, self.cold, self.cold["grids"][0], self.aliases)
            saved = self._save(tmp, self.warm, self.warm["grids"][0], None)
        self.assertEqual(saved["grid"]["dataset"], "dsMntDetailListTemp")

    def test_an_alias_survives_a_later_run_that_saw_only_one_name(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._save(tmp, self.cold, self.cold["grids"][0], self.aliases)
            saved = self._save(tmp, self.warm, self.warm["grids"][0], None)
        self.assertEqual(saved["grid_aliases"], self.aliases)

    def test_a_screen_that_never_rebinds_writes_no_alias_key_at_all(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            saved = self._save(tmp, self.cold, self.cold["grids"][0], None)
        self.assertNotIn("grid_aliases", saved)

    # -- the run ------------------------------------------------------------

    def test_follow_grid_rebind_finds_the_same_component_under_its_new_dataset(self):
        screen = core.Screen(None, "R5216UM00", {"title": "t"}, self.cold)
        with patch.object(core, "discover", return_value=self.warm):
            found = screen.follow_grid_rebind(self.cold["grids"][0])
        self.assertEqual(found["dataset"], "dsMntDetailList")

    def test_follow_grid_rebind_reports_nothing_when_the_binding_is_unchanged(self):
        screen = core.Screen(None, "R5216UM00", {"title": "t"}, self.cold)
        with patch.object(core, "discover", return_value=self.cold):
            self.assertIsNone(screen.follow_grid_rebind(self.cold["grids"][0]))

    def test_follow_grid_rebind_never_borrows_a_different_grid(self):
        # Same dataset appearing under a DIFFERENT component is not a
        # re-bind of this one.
        elsewhere = dict(self.cold, grids=[grid("grdOther", "dsMntDetailList", 300000)])
        screen = core.Screen(None, "R5216UM00", {"title": "t"}, self.cold)
        with patch.object(core, "discover", return_value=elsewhere):
            self.assertIsNone(screen.follow_grid_rebind(self.cold["grids"][0]))

    def test_follow_grid_rebind_never_borrows_a_same_named_grid_on_another_form(self):
        # Component names are unique only WITHIN a form (P3151WM00 has
        # grd00/grd01/grd02 repeated across sibling panels), so the name
        # alone is not an identity - the form path is half of it.
        elsewhere = dict(self.cold, grids=[grid(
            "grdDetail", "dsMntDetailList", 300000,
            path="application.mainframe.winTest_0_1.form.divOtherPanel.form")])
        screen = core.Screen(None, "R5216UM00", {"title": "t"}, self.cold)
        with patch.object(core, "discover", return_value=elsewhere):
            self.assertIsNone(screen.follow_grid_rebind(self.cold["grids"][0]))

    def test_the_binding_is_reconciled_after_inquiry_and_before_giving_up(self):
        # Phase 82.20 widened this from "only on a zero": a placeholder that
        # holds even one header row would have passed a zero-only test.
        import inspect
        src = inspect.getsource(core.run_screen)
        inquiry_at = src.index("rows = screen.inquiry(grid)")
        reconcile_at = src.index("reconcile_result(screen, grid, rows, log=log)")
        empty_at = src.index("explain_empty_result(screen, grid)")
        self.assertLess(inquiry_at, reconcile_at)
        self.assertLess(reconcile_at, empty_at)
        self.assertNotIn("if rows == 0:\n        # Zero from the dataset discovery chose", src)

    def test_the_profile_is_saved_with_the_grid_discovery_saw_not_the_rebound_one(self):
        import inspect
        src = inspect.getsource(core.run_screen)
        self.assertIn("grid=discovered_grid,", src)
        self.assertIn("grid_aliases=grid_aliases,", src)


class ResultIntegrity(unittest.TestCase):
    """HISTORY.md Phase 82.20. R5216UM00 showed how the tool can be confidently
    WRONG without any error: it reported "no rows" beside a screenshot of 259.
    The research behind this (Nexacro's own developer guide, plus live
    probing) found the platform-level tricks a screen can play on a tool that
    reads Datasets: a grid's `binddataset` may be set at runtime; a Dataset
    may carry a client-side `filter()` that changes what `getRowCount()`
    reports; and a form walk that stops early hands back a partial screen."""

    def setUp(self):
        self.g = grid("grdDetail", "dsPlaceholder", 300000)
        self.real = grid("grdDetail", "dsReal", 300000)

    class Stub:
        def __init__(self, rebound=None, totals=None):
            self.warnings, self.ws, self.code = [], None, "X1000UM00"
            self._rebound, self._totals = rebound, totals or {}

        def follow_grid_rebind(self, _grid):
            return self._rebound

        def rows(self, g, limit=-1):
            return {"found": True, "total": self._totals.get(g["dataset"], 0)}

    # -- reconcile_result ---------------------------------------------------

    def test_an_unchanged_binding_is_left_alone(self):
        got = core.reconcile_result(self.Stub(), self.g, 12, log=lambda _m: None)
        self.assertEqual(got, (self.g, 12, {}))

    def test_a_rebound_grid_with_rows_is_followed(self):
        stub = self.Stub(rebound=self.real, totals={"dsReal": 259})
        got = core.reconcile_result(stub, self.g, 0, log=lambda _m: None)
        self.assertEqual(got, (self.real, 259, {"dsReal": "dsPlaceholder"}))

    def test_a_placeholder_holding_a_row_is_followed_too_not_only_an_empty_one(self):
        # The reason the check is no longer "only on a zero": a placeholder
        # with a single header row is NOT zero and would have been exported
        # as the report.
        stub = self.Stub(rebound=self.real, totals={"dsReal": 259})
        got = core.reconcile_result(stub, self.g, 1, log=lambda _m: None)
        self.assertEqual(got[0], self.real)
        self.assertEqual(got[1], 259)

    def test_an_empty_rebound_dataset_is_not_followed_but_the_disagreement_is_reported(self):
        stub = self.Stub(rebound=self.real, totals={"dsReal": 0})
        got = core.reconcile_result(stub, self.g, 12, log=lambda _m: None)
        self.assertEqual(got, (self.g, 12, {}))
        self.assertEqual(len(stub.warnings), 1)
        self.assertIn("may disagree", stub.warnings[0])

    def test_an_empty_rebound_dataset_beside_an_empty_one_is_just_empty(self):
        stub = self.Stub(rebound=self.real, totals={})
        got = core.reconcile_result(stub, self.g, 0, log=lambda _m: None)
        self.assertEqual(got, (self.g, 0, {}))
        self.assertEqual(stub.warnings, [])

    # -- explain_empty_result -----------------------------------------------

    def _info(self, *grids):
        return {"grids": list(grids)}

    def test_an_empty_result_names_the_other_grid_that_has_rows(self):
        other = grid("grdSecond", "dsSecond", 200000)
        stub = self.Stub(totals={"dsSecond": 67})
        with patch.object(core, "discover", return_value=self._info(self.g, other)):
            msg = core.explain_empty_result(stub, self.g)
        self.assertIn("grdSecond", msg)
        self.assertIn("67 rows", msg)
        self.assertIn("--grid", msg)
        self.assertIn("nothing was guessed", msg)

    def test_an_empty_result_with_no_other_rows_is_the_plain_message(self):
        stub = self.Stub(totals={})
        with patch.object(core, "discover", return_value=self._info(self.g)):
            msg = core.explain_empty_result(stub, self.g)
        self.assertEqual(msg, "the query returned no rows - nothing exported")

    def test_explaining_never_masks_the_original_error_if_it_cannot_look(self):
        with patch.object(core, "discover", side_effect=RuntimeError("boom")):
            msg = core.explain_empty_result(self.Stub(), self.g)
        self.assertEqual(msg, "the query returned no rows - nothing exported")

    def test_explaining_never_switches_the_run_to_another_grid(self):
        # Which grid is the report is the person's call on a master/detail
        # screen; the message offers it, the code never takes it.
        import inspect
        self.assertNotIn("grid = ", inspect.getsource(core.explain_empty_result))

    # -- filtered_result_note -----------------------------------------------

    def test_a_client_side_filter_that_hides_rows_is_reported_with_both_numbers(self):
        note = core.filtered_result_note(
            {"total": 20, "unfiltered": 37, "filterstr": "gubun!='RB'"})
        self.assertIn("20 of 37", note)
        self.assertIn("gubun!='RB'", note)

    def test_a_filter_that_hides_nothing_is_not_reported(self):
        self.assertIsNone(core.filtered_result_note(
            {"total": 6, "unfiltered": 6, "filterstr": "x==1"}))

    def test_no_filter_or_an_unreadable_count_is_not_reported(self):
        self.assertIsNone(core.filtered_result_note({"total": 9, "filterstr": ""}))
        self.assertIsNone(core.filtered_result_note({"total": 9, "filterstr": "x==1"}))
        self.assertIsNone(core.filtered_result_note(None))

    # -- unchanged_result_note / grid_is_proven (HISTORY.md Phase 82.21) ------

    def test_a_result_that_never_moved_is_flagged(self):
        # R3220UM00: 37 rows before Inquiry, 37 after, never changed - the
        # screen's static "Formula" legend, exported as the report.
        note = core.unchanged_result_note({"before": 37, "changed": False}, 37)
        self.assertIn("37 rows before Inquiry", note)
        self.assertIn("static content", note)

    def test_a_result_that_moved_is_not_flagged(self):
        self.assertIsNone(core.unchanged_result_note({"before": 0, "changed": True}, 259))

    def test_a_result_that_cleared_and_refilled_to_the_same_count_is_not_flagged(self):
        # Nexacro clears the dataset on Inquiry; seeing that happen IS the
        # evidence the query ran, even if the answer came back identical.
        self.assertIsNone(core.unchanged_result_note({"before": 5, "changed": True}, 5))

    def test_a_different_count_after_is_not_flagged(self):
        self.assertIsNone(core.unchanged_result_note({"before": 10, "changed": False}, 12))

    def test_an_empty_or_unknown_result_is_not_flagged(self):
        self.assertIsNone(core.unchanged_result_note({"before": 0, "changed": False}, 0))
        self.assertIsNone(core.unchanged_result_note({}, 5))
        self.assertIsNone(core.unchanged_result_note(None, 5))

    def test_a_grid_the_profile_already_vetted_is_proven(self):
        profile = {"grid": {"dataset": "dsGrpSummary"}}
        self.assertTrue(core.grid_is_proven(profile, grid("g", "dsGrpSummary", 1)))

    def test_a_different_grid_than_the_profile_names_is_not_proven(self):
        # The exact R3220 mistake: the profile (or default) said one dataset,
        # a --grid override chose another.
        profile = {"grid": {"dataset": "dsGrpSummary"}}
        self.assertFalse(core.grid_is_proven(profile, grid("g", "dsOperAnalCalc", 1)))

    def test_no_profile_means_nothing_is_proven(self):
        # First recording, and --relearn (which loads no profile).
        self.assertFalse(core.grid_is_proven(None, grid("g", "dsX", 1)))
        self.assertFalse(core.grid_is_proven({}, grid("g", "dsX", 1)))

    def test_a_rebound_grid_is_proven_under_either_of_its_names(self):
        profile = {"grid": {"dataset": "dsPlaceholder"},
                   "grid_aliases": {"dsReal": "dsPlaceholder"}}
        self.assertTrue(core.grid_is_proven(profile, grid("g", "dsReal", 1)))
        self.assertTrue(core.grid_is_proven(profile, grid("g", "dsPlaceholder", 1)))

    def test_a_profile_that_stored_the_rebound_name_is_proven_against_the_placeholder(self):
        # The other direction: remembered under the re-bound name, met under
        # the placeholder name in a cold window.
        profile = {"grid": {"dataset": "dsReal"},
                   "grid_aliases": {"dsReal": "dsPlaceholder"}}
        self.assertTrue(core.grid_is_proven(profile, grid("g", "dsPlaceholder", 1)))

    def test_run_screen_only_asks_about_an_unproven_grid(self):
        import inspect
        src = inspect.getsource(core.run_screen)
        proven_at = src.index("if not grid_is_proven(profile, discovered_grid):")
        note_at = src.index("unchanged_result_note(getattr(screen")
        self.assertLess(proven_at, note_at)

    def test_a_suspect_result_is_exported_but_never_remembered(self):
        # R3220UM00: the static-legend run "learned: saved to R3220UM00.json",
        # making the wrong grid the default for every later replay.
        import inspect
        src = inspect.getsource(core.run_screen)
        self.assertIn("result_suspect = True", src)
        skip_at = src.index("if use_profile and result_suspect:")
        save_at = src.index("elif use_profile:")
        self.assertLess(skip_at, save_at)
        self.assertIn("not remembered for next time", src)

    def test_the_poll_reports_what_it_saw_and_the_screen_keeps_it(self):
        import inspect
        self.assertIn("report.update(before=before, changed=tracker.changed)",
                      inspect.getsource(core.poll_inquiry))
        self.assertIn("report=self.last_inquiry", inspect.getsource(core.Screen.inquiry))

    # -- unverified_date_sets -----------------------------------------------

    def test_a_date_typed_with_set_and_no_verify_is_called_out(self):
        applied = [(flt(column="startDay", control="mskFrom", label="Period"), "20260919")]
        self.assertEqual(core.unverified_date_sets(applied, None), ["Period"])

    def test_from_and_to_sharing_one_label_are_called_out_once(self):
        applied = [(flt(column="startDay", control="mskFrom", label="Period"), "20260919"),
                   (flt(column="endDay", control="mskTo", label="Period"), "20260919")]
        self.assertEqual(core.unverified_date_sets(applied, None), ["Period"])

    def test_a_verify_silences_it(self):
        applied = [(flt(column="startDay", control="mskFrom", label="Period"), "20260919")]
        self.assertEqual(core.unverified_date_sets(applied, "planYmd"), [])

    def test_a_non_date_set_is_never_called_a_date(self):
        applied = [(flt(column="orderNo", control="edtOrder", label="Order"), "123")]
        self.assertEqual(core.unverified_date_sets(applied, None), [])

    # -- discovery that was cut short ---------------------------------------

    def test_a_truncated_form_walk_is_refused(self):
        self.assertIn("cut short", core.discovery_cut({"truncated": True}))

    def test_a_result_list_that_lost_entries_is_refused(self):
        msg = core.discovery_cut({"grids": [1, 2], "totals": {"grids": 30}})
        self.assertIn("2 of this screen's 30 result grids", msg)

    def test_a_complete_reading_passes(self):
        self.assertIsNone(core.discovery_cut(
            {"grids": [1, 2], "unbound": [], "totals": {"grids": 2, "unbound": 0}}))
        self.assertIsNone(core.discovery_cut({}))
        self.assertIsNone(core.discovery_cut(None))

    def test_discover_raises_rather_than_return_a_cut_reading(self):
        with patch.object(core, "evaluate", return_value={"found": True, "truncated": True}):
            with self.assertRaisesRegex(RuntimeError, "cut short"):
                core.discover(None, "X1000UM00")

    # -- the JavaScript itself (source level; no mock G-MES, CLAUDE.md 4.3) ---

    def test_the_form_walk_records_that_it_was_cut_and_the_old_cap_is_gone(self):
        self.assertIn("_findForms.truncated = true", gmes_data.JS_HELPERS)
        self.assertIsNone(re.search(r"hits\.length > 400\b", gmes_data.JS_HELPERS))

    def test_discovery_reports_the_walk_state_and_the_true_list_lengths(self):
        self.assertIn("truncated: !!_findForms.truncated", core.JS_DISCOVER)
        self.assertIn("totals: {grids: grids.length, unbound: trulyUnbound.length}",
                      core.JS_DISCOVER)
        self.assertNotIn("grids.slice(0, 8)", core.JS_DISCOVER)
        self.assertNotIn("unbound: trulyUnbound.slice(0, 40)", core.JS_DISCOVER)
        # "Not the old literal" is not enough - the new caps must actually be
        # far above what a real screen has (the largest seen: 8 grids).
        caps = {k: int(v) for k, v in
                re.findall(r"(GRID_CAP|UNBOUND_CAP) = (\d+)", core.JS_DISCOVER)}
        self.assertGreaterEqual(caps["GRID_CAP"], 24)
        self.assertGreaterEqual(caps["UNBOUND_CAP"], 200)

    def test_a_dataset_read_reports_an_active_client_side_filter(self):
        js = gmes_data.js_read("X1000UM00", "dsX", -1, 0)
        self.assertIn("getRowCountNF", js)
        self.assertIn("filterstr: filterstr, unfiltered: unfiltered", js)

    def test_run_screen_wires_all_of_it_in(self):
        import inspect
        src = inspect.getsource(core.run_screen)
        for needle in ("reconcile_result(", "explain_empty_result(",
                       "filtered_result_note(", "unverified_date_sets("):
            with self.subTest(needle=needle):
                self.assertIn(needle, src)


class Profiles(unittest.TestCase):
    """What the tool remembers after a run that worked, and - more
    importantly - when it must refuse to trust that memory."""

    def setUp(self):
        import gmes_profile
        self.p = gmes_profile
        self.info = {
            "filters": [flt(column="paramFromDate", control="mskDateFrom"),
                        flt(column="paramEndDate", control="mskDateTo"),
                        flt(column="paramPo", control="edtPo")],
            "unbound": [],
            "grids": [grid("grdMain", "dsMasterProdPlan", 400000)],
        }

    def profile_for(self, info):
        return {"from": self.p.field_ref(info["filters"][0]),
                "to": self.p.field_ref(info["filters"][1]),
                "grid": self.p.grid_ref(info["grids"][0]),
                "fingerprint": self.p.fingerprint(info)}

    def test_an_unchanged_screen_has_no_problems(self):
        self.assertEqual(self.p.describe_change(self.profile_for(self.info),
                                                self.info), [])

    def test_the_same_screen_fingerprints_the_same_twice(self):
        self.assertEqual(self.p.fingerprint(self.info), self.p.fingerprint(self.info))

    def test_a_renamed_date_field_is_caught(self):
        profile = self.profile_for(self.info)
        changed = dict(self.info)
        changed["filters"] = [flt(column="paramFromDate", control="mskDateFrom"),
                              flt(column="paramToDate", control="mskDateTo"),
                              flt(column="paramPo", control="edtPo")]
        problems = self.p.describe_change(profile, changed)
        self.assertTrue(problems)
        self.assertIn("paramEndDate", problems[0])

    def test_a_missing_grid_is_caught(self):
        profile = self.profile_for(self.info)
        changed = dict(self.info, grids=[grid("grdOther", "dsSomethingElse", 10)])
        self.assertTrue(self.p.describe_change(profile, changed))

    def test_a_control_appearing_or_vanishing_is_not_a_change(self):
        # Unbound inputs are collected only when visible, and visibility moves
        # with scrolling and late-rendering panels. Including them made a
        # screen "change" between two runs seconds apart, so the profile threw
        # itself away every time.
        profile = self.profile_for(self.info)
        scrolled = dict(self.info,
                        unbound=[flt(control="edtLotNo", bound=False)])
        self.assertEqual(self.p.describe_change(profile, scrolled), [])

    def test_the_same_column_on_a_different_control_is_not_a_change(self):
        # One column can be bound to two controls; which one is recorded
        # depends on which was visible.
        profile = self.profile_for(self.info)
        rebound = dict(self.info)
        rebound["filters"] = [flt(column="paramFromDate", control="mskDateFrom2"),
                              flt(column="paramEndDate", control="mskDateTo"),
                              flt(column="paramPo", control="edtPo")]
        self.assertEqual(self.p.describe_change(profile, rebound), [])

    def test_a_second_grid_on_the_same_dataset_is_not_a_change(self):
        # The Excel export leaves a clone (grdPrnMpp__EXCEL__) bound to the
        # same dataset, so the screen "changed" after every export.
        profile = self.profile_for(self.info)
        after_export = dict(self.info,
                            grids=self.info["grids"] +
                            [grid("grdMain__EXCEL__", "dsMasterProdPlan", 0)])
        self.assertEqual(self.p.describe_change(profile, after_export), [])

    def test_a_new_filter_elsewhere_is_reported_not_ignored(self):
        # Nothing the profile uses moved, but it is not the same screen -
        # worth saying so rather than replaying in silence.
        profile = self.profile_for(self.info)
        changed = dict(self.info)
        changed["filters"] = self.info["filters"] + [flt(column="paramNew",
                                                         control="edtNew")]
        self.assertTrue(self.p.describe_change(profile, changed))

    def test_a_saved_reference_never_holds_a_value_or_an_id(self):
        # A form tree contains live session tokens; only named fields are
        # ever copied out.
        ref = self.p.field_ref(flt(column="paramPo", value="011074232146"))
        self.assertNotIn("value", ref)
        self.assertNotIn("id", ref)
        self.assertEqual(set(ref), {"dataset", "column", "control", "form",
                                    "label", "stable_path"})


class ShippableProfiles(unittest.TestCase):
    """What the tool knows about a screen can be given away. What a user did
    with it cannot.

    The expensive half of a profile - which control is "from", which grid
    holds the result, where the division tree lives - costs a RECORD run per
    screen and is true for anyone with access to that screen. The other half
    is production data (CLAUDE.md 2.4). These tests pin the line between
    them, because the cost of getting it wrong is business data in a public
    repository."""

    FULL = {
        "screen": "P1112UM00",
        "title": "Production Plan by Order(Line)",
        "menuId": "PPM0219",
        "learned": "2026-09-15 10:00:00",
        "fingerprint": "abc123",
        "opening_fingerprint": "def456",
        "from": {"dataset": "dsFilterDVO", "column": "paramFromDate",
                 "control": "mskDateFrom", "form": "P1112WF00", "label": "From"},
        "to": {"dataset": "dsFilterDVO", "column": "paramEndDate",
               "control": "mskDateTo", "form": "P1112WF00", "label": "To"},
        "division": {"form": "OrgCategory_GDS",
                     "dataset": "dsCatCommonTreeNodeDVO", "entry": "VD"},
        "grid": {"name": "grdMain", "dataset": "dsMasterProdPlan",
                 "form": "P1112WM00"},
        "options": ["Create Date"],
        "values": {"division": "VD", "from": "20260909", "to": "20260909",
                   "verify": "creYmd",
                   "sets": {"Production Order": "011074232146"}},
        "proved": {"rows": 790,
                   "command": "--division VD --from 20260909 --to 20260909"},
    }

    def setUp(self):
        import gmes_profile
        self.p = gmes_profile

    def test_the_structural_half_is_kept(self):
        out = self.p.shippable(self.FULL)
        self.assertEqual(out["screen"], "P1112UM00")
        self.assertEqual(out["from"]["column"], "paramFromDate")
        self.assertEqual(out["grid"]["dataset"], "dsMasterProdPlan")
        self.assertEqual(out["fingerprint"], "abc123")

    def test_options_are_a_report_preset_not_screen_structure_so_they_never_ship(self):
        # HISTORY.md Phase 79.6: "Create Date" vs "Plan Date" is exactly the
        # kind of decision this file's own docstring says nothing on the
        # screen records - the same reasoning that already keeps a ticked
        # DIVISION out of the shipped half (see the test above this one).
        # Shipping one person's option choice let a new user silently
        # inherit somebody else's answer to a question they were never
        # asked. Local replay for a machine that HAS run the screen is
        # untouched - see LocalOptionsSurviveShipping below.
        out = self.p.shippable(self.FULL)
        self.assertNotIn("options", out)

    def test_no_value_or_command_can_reach_the_shipped_half(self):
        out = self.p.shippable(self.FULL)
        self.assertNotIn("values", out)
        self.assertNotIn("proved", out)
        # Checked as text too, so a value nested anywhere still fails this.
        blob = json.dumps(out)
        for secret in ("011074232146", "20260909", "790",
                       "--division", "VD"):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, blob,
                                 f"{secret!r} reached the shipped profile")

    def test_the_division_tree_location_ships_but_the_division_does_not(self):
        out = self.p.shippable(self.FULL)
        self.assertEqual(out["division"]["dataset"], "dsCatCommonTreeNodeDVO")
        self.assertNotIn("entry", out["division"],
                         "the ticked division is the user's own context")

    def test_it_is_an_allowlist_so_a_new_field_cannot_leak(self):
        # A field added to save() in future must be considered before it can
        # ship, rather than leaking because nobody remembered to exclude it.
        with_extra = dict(self.FULL, someFutureField="a plant code, perhaps")
        self.assertNotIn("someFutureField", self.p.shippable(with_extra))

    def test_shippable_of_nothing_is_nothing(self):
        self.assertIsNone(self.p.shippable(None))


class ShippedAndLocalMerge(unittest.TestCase):
    """A new user has only the shipped half and the screen still works; once
    they prove it themselves, their own file wins."""

    def setUp(self):
        import tempfile, shutil, gmes_profile
        self.p = gmes_profile
        self.tmp = tempfile.mkdtemp(prefix="gmes-profile-merge-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.shipped = os.path.join(self.tmp, "shipped")
        self.local = os.path.join(self.tmp, "local")
        os.makedirs(self.shipped)
        os.makedirs(self.local)
        self._patch = patch.multiple(gmes_profile,
                                     SHIPPED_DIR=self.shipped,
                                     SCREENS_DIR=self.local)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def _write(self, directory, code, payload):
        with open(os.path.join(directory, f"{code}.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def test_a_new_user_gets_the_shipped_screen(self):
        self._write(self.shipped, "P1112UM00",
                    {"screen": "P1112UM00", "grid": {"dataset": "dsMasterProdPlan"}})
        loaded = self.p.load("P1112UM00")
        self.assertEqual(loaded["grid"]["dataset"], "dsMasterProdPlan")
        self.assertNotIn("values", loaded)

    def test_a_locally_proved_profile_wins(self):
        self._write(self.shipped, "P1112UM00",
                    {"screen": "P1112UM00", "fingerprint": "shipped"})
        self._write(self.local, "P1112UM00",
                    {"screen": "P1112UM00", "fingerprint": "mine",
                     "values": {"division": "VD"}})
        loaded = self.p.load("P1112UM00")
        self.assertEqual(loaded["fingerprint"], "mine")
        self.assertEqual(loaded["values"]["division"], "VD")

    def test_neither_present_is_still_none(self):
        self.assertIsNone(self.p.load("P9999UM00"))

    def test_known_lists_shipped_and_local_together_without_duplicates(self):
        self._write(self.shipped, "P1112UM00", {"screen": "P1112UM00"})
        self._write(self.shipped, "P1111UM00", {"screen": "P1111UM00"})
        self._write(self.local, "P1112UM00",
                    {"screen": "P1112UM00", "learned": "2026-09-15 10:00:00"})
        codes = [p["screen"] for p in self.p.known()]
        self.assertEqual(sorted(codes), ["P1111UM00", "P1112UM00"])
        # The one proved here sorts first - it has a timestamp, shipped ones do not.
        self.assertEqual(codes[0], "P1112UM00")

    def test_export_writes_only_the_structural_half(self):
        self._write(self.local, "P1112UM00", ShippableProfiles.FULL)
        written = self.p.export_shippable("P1112UM00", dest_dir=self.shipped)
        self.assertTrue(os.path.isfile(written))
        with open(written, encoding="utf-8") as fh:
            blob = fh.read()
        self.assertNotIn("011074232146", blob)
        self.assertNotIn("proved", blob)
        self.assertIn("dsMasterProdPlan", blob)

    def test_exporting_a_screen_with_nothing_local_is_not_an_error(self):
        self.assertIsNone(self.p.export_shippable("P1111UM00", dest_dir=self.shipped))

    def test_a_brand_new_machine_inherits_no_options_preset(self):
        # HISTORY.md Phase 79.6, the exact scenario: the shipped half
        # (everyone's) never carries an option choice, so a new user makes
        # this decision themselves the first time - the same as division
        # and dates - rather than silently inheriting someone else's answer.
        self._write(self.shipped, "P1112UM00",
                    {"screen": "P1112UM00", "grid": {"dataset": "dsMasterProdPlan"}})
        loaded = self.p.load("P1112UM00")
        self.assertNotIn("options", loaded)

    def test_a_machine_that_has_proved_the_screen_keeps_its_own_option_choice(self):
        # The LOCAL half is untouched by this phase - a machine that has run
        # the screen successfully once still replays exactly what it proved,
        # with no re-recording needed.
        self._write(self.shipped, "P1112UM00",
                    {"screen": "P1112UM00", "grid": {"dataset": "dsMasterProdPlan"}})
        self._write(self.local, "P1112UM00",
                    {"screen": "P1112UM00",
                     "options": [{"key": "create", "name": "btnCreate",
                                 "path": "", "label": "Create Date"}]})
        loaded = self.p.load("P1112UM00")
        self.assertEqual(loaded["options"][0]["key"], "create")

    def test_exporting_a_proved_screen_no_longer_writes_its_option_choice(self):
        self._write(self.local, "P1112UM00", ShippableProfiles.FULL)
        written = self.p.export_shippable("P1112UM00", dest_dir=self.shipped)
        with open(written, encoding="utf-8") as fh:
            raw = fh.read()
        self.assertNotIn("options", json.loads(raw))
        self.assertNotIn("Create Date", raw)


class RememberedValues(unittest.TestCase):
    """A remembered value must survive a run that did not supply one.

    P1111UM00 was recorded with VD and a date range, then run once with
    everything blank, and its memory came back empty. "Never forget" has to
    mean that an empty answer does not erase a remembered one."""

    def setUp(self):
        import gmes_profile
        self.p = gmes_profile
        self.previous = {"values": {"division": "VD", "from": "20260909",
                                    "to": "20260909", "sets": {}}}

    def test_a_blank_run_does_not_erase_anything(self):
        merged = self.p._merge_values(
            self.previous, {"division": "", "from": "", "to": "", "sets": {}})
        self.assertEqual(merged["division"], "VD")
        self.assertEqual(merged["from"], "20260909")

    def test_a_supplied_value_replaces_the_old_one(self):
        merged = self.p._merge_values(
            self.previous, {"division": "MOBILE", "from": "", "to": "", "sets": {}})
        self.assertEqual(merged["division"], "MOBILE")
        self.assertEqual(merged["to"], "20260909")     # untouched

    def test_first_ever_save_keeps_what_it_was_given(self):
        merged = self.p._merge_values(None, {"division": "VD", "from": "20260901",
                                             "to": "20260902", "sets": {}})
        self.assertEqual(merged, {"division": "VD", "from": "20260901",
                                  "to": "20260902", "sets": {}})

    def test_values_are_recovered_from_an_older_profile(self):
        # Profiles written before the values block still carry the command
        # that proved them; re-teaching would be absurd.
        old = {"proved": {"rows": 800,
                          "command": "--division VD --from 20260909 --to 20260909"}}
        self.assertEqual(self.p.last_values(old)["division"], "VD")
        self.assertEqual(self.p.last_values(old)["to"], "20260909")

    def test_none_in_a_recovered_command_is_not_a_value(self):
        old = {"proved": {"command": "--division None --from None --to None"}}
        self.assertEqual(self.p.last_values(old), {})


class ProfileReplayLifecycle(unittest.TestCase):
    """A left-panel option creates a second valid screen shape.

    The pre-d7886cd core saved only the post-option shape, then compared it
    with the next opening shape before reapplying the option and refused a
    valid replay.
    """

    class FakeScreen:
        def __init__(self, opening, after_option):
            self._info = opening
            self.after_option = after_option
            self.title = "Profile lifecycle"
            self.menu_id = "M-1"
            self.win_id = "win_1"
            self.warnings = []
            self.last_tree = None
            self.options_set = []
            self._selected_name = None

        @property
        def info(self):
            return self._info

        @property
        def filters(self):
            return self.info["filters"]

        @property
        def unbound(self):
            return self.info.get("unbound", [])

        def grid(self, _preferred=None):
            return self.info["grids"][0]

        def refresh(self):
            return self.info

        def options(self):
            # Final Intent Verification (step 7.5) re-reads this right before
            # Inquiry; it must agree with whatever set_option() last resolved,
            # exactly as the real Screen's left_options() would.
            if self._selected_name is None:
                return []
            return [{"name": self._selected_name, "label": self._selected_name,
                     "state": "selected"}]

        def set_option(self, wanted):
            self.options_set.append(wanted)
            self._info = self.after_option
            # Phase 76 contract: the resolved STABLE identity comes back, not
            # the text it was asked with, so run_screen can remember the
            # identity instead of a label that depends on the UI language.
            # `wanted` is a plain string on a first RECORD, and the profile's
            # own saved {key, name, path, label} dict on a replay - resolved
            # the same way the real Screen.set_option()/resolve_option() do,
            # not by str()'ing whichever shape happened to arrive.
            name = wanted.get("name") if isinstance(wanted, dict) else str(wanted)
            self._selected_name = name
            return {"outcome": f"{name} -> selected",
                    "matched_by": "component name",
                    "key": core.option_key(name),
                    "name": name, "path": "", "label": name}

        def clear_stale(self, _keep):
            return []

        def inquiry(self, _grid):
            return 1

        # The real Screen answers both after every Inquiry (HISTORY.md
        # Phase 82.20): the grid's live binding, and the result's row count.
        def follow_grid_rebind(self, _grid):
            return None

        def rows(self, _grid, limit=-1):
            return {"found": True, "total": 1, "rows": []}

    def test_option_profile_checks_opening_then_post_option_shape_and_refuses_real_opening_drift(self):
        import gmes_profile

        opening = {"filters": [flt(column="initialDate", control="mskInitial")],
                   "unbound": [], "grids": [grid("grdInitial", "dsInitial", 100)]}
        post_option = {"filters": [flt(column="planDate", control="mskPlan")],
                       "unbound": [], "grids": [grid("grdPlan", "dsPlan", 100)]}
        changed_opening = {"filters": [flt(column="changedDate", control="mskChanged")],
                           "unbound": [], "grids": [grid("grdInitial", "dsInitial", 100)]}
        learned = self.FakeScreen(opening, post_option)
        replay = self.FakeScreen(opening, post_option)
        drifted = self.FakeScreen(changed_opening, post_option)

        store = {}

        def load_profile(code):
            return store.get(code)

        def save_profile(code, _title, _menu_id, info, *, grid=None, options=(),
                         opening_info=None, **_unused):
            store[code] = {
                "fingerprint": gmes_profile.fingerprint(info),
                "opening_fingerprint": gmes_profile.fingerprint(opening_info or info),
                "grid": gmes_profile.grid_ref(grid),
                "options": list(options),
            }
            return "test-profile.json"

        with patch.object(gmes_profile, "load", side_effect=load_profile), \
             patch.object(gmes_profile, "save", side_effect=save_profile) as save, \
             patch.object(core, "open_screen", side_effect=[learned, replay, drifted]), \
             patch.object(core, "org_selection", return_value={"found": False}):
            first = core.run_screen(None, "P1234UM00", options=("Plan Date",),
                                    export="none", log=lambda _message: None)
            self.assertTrue(first["ok"])
            self.assertEqual(store["P1234UM00"]["opening_fingerprint"],
                             gmes_profile.fingerprint(opening))
            self.assertEqual(store["P1234UM00"]["fingerprint"],
                             gmes_profile.fingerprint(post_option))

            second = core.run_screen(None, "P1234UM00", export="none", log=lambda _message: None)
            self.assertTrue(second["ok"])
            # Replay re-applies the STABLE IDENTITY the first run resolved, not
            # the "Plan Date" text it was originally asked with. That is what
            # survives a UI-language change (HISTORY.md Phase 76); the label is
            # carried along only so a person can read their own profile.
            self.assertEqual(len(replay.options_set), 1)
            replayed = replay.options_set[0]
            self.assertIsInstance(replayed, dict)
            self.assertEqual(replayed["name"], "Plan Date")
            self.assertEqual(replayed["key"], core.option_key("Plan Date"))
            self.assertEqual(store["P1234UM00"]["grid"]["dataset"], "dsPlan")

            before_failed_replay = deepcopy(store["P1234UM00"])
            with self.assertRaisesRegex(RuntimeError, "remembered screen shape changed"):
                core.run_screen(None, "P1234UM00", export="none", log=lambda _message: None)
            self.assertEqual(drifted.options_set, [])
            self.assertEqual(store["P1234UM00"], before_failed_replay)
            self.assertEqual(save.call_count, 2)


class AutoReplayFromSavedProfile(unittest.TestCase):
    """HISTORY.md Phase 82.9, live-caught while recording M3912UM00
    together with the project owner: `run_screen()` already re-applied a
    taught screen's OPTIONS automatically when a call named none of its
    own, but division, dates and `--set` filters all still required the
    caller to retype exactly what a previous run had already proven -
    `run_gmes_workflow.py`'s interactive "Run it?" replay has always done
    this via `gmes_profile.last_values()`, but only there. A caller with
    no terminal to answer a prompt - `gmes_report.py run <CODE>` with no
    other flags, and therefore `GMES_Workflow.bat <CODE>` too - got none
    of it."""

    class FakeScreen:
        def __init__(self, info):
            self._info = info
            self.title, self.menu_id, self.win_id = "Assign Range", "M-1", "win_1"
            self.warnings = []
            self.last_tree = None
            self.select_org_calls = []
            self.date_range_calls = []
            self.set_filter_calls = []

        @property
        def info(self):
            return self._info

        @property
        def filters(self):
            return self._info["filters"]

        @property
        def unbound(self):
            return self._info.get("unbound", [])

        def grid(self, _preferred=None):
            return self._info["grids"][0]

        def refresh(self):
            return self._info

        def options(self):
            return []

        def _set_filter_value(self, column, value):
            # Final Intent Verification (step 7.5) re-reads self.info right
            # after these writes via refresh() - it must see the value that
            # was actually just set, exactly as a real Screen would.
            for f in self._info["filters"]:
                if f.get("column") == column:
                    f["value"] = value
                    return

        def select_org(self, names, tree=None, prefer=None):
            self.select_org_calls.append(names)
            return {"ticked": [{"name": names if isinstance(names, str) else names[0]}],
                    "cleared": [], "confirmed": names}

        def set_date_range(self, from_value, to_value, profile=None):
            self.date_range_calls.append((from_value, to_value))
            if not from_value:
                return []
            f = flt(column="fromYmd", control="mskFrom")
            self._set_filter_value("fromYmd", from_value)
            return [(f, from_value)]

        def clear_stale(self, _keep):
            return []

        def set_filter(self, key, value):
            self.set_filter_calls.append((key, value))
            f = flt(column=key, control="edt" + key, label=key)
            self._set_filter_value(key, value)
            return f, value

        def inquiry(self, _grid):
            return 1

        # The real Screen answers both after every Inquiry (HISTORY.md
        # Phase 82.20): the grid's live binding, and the result's row count.
        def follow_grid_rebind(self, _grid):
            return None

        def rows(self, _grid, limit=-1):
            return {"found": True, "total": 1, "rows": []}

        def verify_column(self, _grid, column, expected, strict=True):
            self.verify_calls = getattr(self, "verify_calls", [])
            self.verify_calls.append((column, expected))
            return [expected]

    def make_screen(self):
        return self.FakeScreen({
            "filters": [flt(column="fromYmd", control="mskFrom"),
                       flt(column="lotNo", control="edtLot")],
            "unbound": [], "grids": [grid("grdMain", "dsMain", 100)]})

    def test_a_bare_replay_pulls_division_dates_and_sets_from_the_profile(self):
        import gmes_profile
        screen = self.make_screen()
        fp = gmes_profile.fingerprint(screen.info)
        profile = {"fingerprint": fp, "opening_fingerprint": fp,
                  "grid": {"dataset": "dsMain"}, "options": [],
                  "values": {"division": "SEEG-P", "from": "20260901",
                            "to": "20260901", "sets": {"lotNo": "ABC123"},
                            "verify": "fromYmd"}}
        with patch.object(gmes_profile, "load", return_value=profile), \
             patch.object(gmes_profile, "save", return_value="x.json"), \
             patch.object(core, "open_screen", return_value=screen), \
             patch.object(core, "org_selection", return_value={"found": True, "org": "SEEG-P"}):
            result = core.run_screen(None, "M3912UM00", export="none",
                                     log=lambda _m: None)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(screen.select_org_calls, ["SEEG-P"])
        self.assertEqual(screen.date_range_calls, [("20260901", "20260901")])
        self.assertEqual(screen.set_filter_calls, [("lotNo", "ABC123")])
        # verify is replayed alongside the dates it was originally paired
        # with, not left to trip run_screen()'s own
        # "a date-constrained run requires --verify" refusal.
        self.assertEqual(screen.verify_calls, [("fromYmd", "20260901")])

    def test_an_explicit_argument_always_wins_over_the_saved_one(self):
        import gmes_profile
        screen = self.make_screen()
        fp = gmes_profile.fingerprint(screen.info)
        profile = {"fingerprint": fp, "opening_fingerprint": fp,
                  "grid": {"dataset": "dsMain"}, "options": [],
                  "values": {"division": "SEEG-P", "sets": {}}}
        with patch.object(gmes_profile, "load", return_value=profile), \
             patch.object(gmes_profile, "save", return_value="x.json"), \
             patch.object(core, "open_screen", return_value=screen), \
             patch.object(core, "org_selection", return_value={"found": True, "org": "MOBILE"}):
            result = core.run_screen(None, "M3912UM00", division="MOBILE",
                                     export="none", log=lambda _m: None)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(screen.select_org_calls, ["MOBILE"])

    def test_no_profile_leaves_the_old_behaviour_unchanged(self):
        import gmes_profile
        screen = self.make_screen()
        with patch.object(gmes_profile, "load", return_value=None), \
             patch.object(gmes_profile, "save", return_value="x.json"), \
             patch.object(core, "open_screen", return_value=screen), \
             patch.object(core, "org_selection", return_value={"found": False}):
            result = core.run_screen(None, "M3912UM00", export="none",
                                     log=lambda _m: None)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(screen.select_org_calls, [])   # nothing to replay, nothing ticked
        self.assertEqual(screen.date_range_calls, [])


class IntentMismatches(unittest.TestCase):
    """HISTORY.md - external review of 8ac502a, finding #4: `intent_mismatches()`
    is the pure decision logic behind run_screen()'s step 7.5, tested directly
    the way `InquirySettle` is - the browser-driven caller (`screen.refresh()`
    et al.) cannot run offline (CLAUDE.md 4.3), but what counts as a mismatch
    is ordinary Python and belongs under a real test."""

    def test_nothing_asked_for_is_never_a_mismatch(self):
        self.assertEqual(core.intent_mismatches({"filters": [], "unbound": []}, []), [])

    def test_an_option_still_selected_is_fine(self):
        resolved = [{"key": "k", "name": "btnCreate", "path": "", "label": "Create Date"}]
        fresh_options = [{"name": "btnCreate", "state": "selected"}]
        self.assertEqual(
            core.intent_mismatches({"filters": [], "unbound": []}, fresh_options,
                                   resolved_options=resolved), [])

    def test_an_option_that_reverted_to_deselected_is_caught(self):
        # Exactly the reviewer's scenario: a LATER step's oncolumnchanged
        # handler silently undoes an option this run already confirmed once.
        resolved = [{"key": "k", "name": "btnCreate", "path": "", "label": "Create Date"}]
        fresh_options = [{"name": "btnCreate", "state": "not selected"}]
        problems = core.intent_mismatches({"filters": [], "unbound": []}, fresh_options,
                                          resolved_options=resolved)
        self.assertEqual(len(problems), 1)
        self.assertIn("Create Date", problems[0])
        self.assertIn("no longer selected", problems[0])

    def test_an_option_that_vanished_entirely_is_caught(self):
        resolved = [{"key": "k", "name": "btnCreate", "path": "", "label": "Create Date"}]
        problems = core.intent_mismatches({"filters": [], "unbound": []}, [],
                                          resolved_options=resolved)
        self.assertIn("no longer on the screen", problems[0])

    def test_a_date_field_that_reverted_is_caught(self):
        written = flt(column="planYmd", dataset="dsFilterDVO")
        fresh = {"filters": [flt(column="planYmd", dataset="dsFilterDVO", value="20260101")],
                "unbound": []}
        problems = core.intent_mismatches(fresh, [], date_fields=[(written, "20260915")])
        self.assertEqual(len(problems), 1)
        self.assertIn("20260101", problems[0])
        self.assertIn("20260915", problems[0])

    def test_a_date_field_that_still_holds_its_value_is_fine(self):
        written = flt(column="planYmd", dataset="dsFilterDVO")
        fresh = {"filters": [flt(column="planYmd", dataset="dsFilterDVO", value="20260915")],
                "unbound": []}
        self.assertEqual(
            core.intent_mismatches(fresh, [], date_fields=[(written, "20260915")]), [])

    def test_digit_equivalent_dates_are_not_a_false_positive(self):
        # values_match() already treats 2026-09-15 == 20260915; this check
        # must reuse that, not a stricter string comparison.
        written = flt(column="planYmd", dataset="dsFilterDVO")
        fresh = {"filters": [flt(column="planYmd", dataset="dsFilterDVO",
                               value="2026-09-15")], "unbound": []}
        self.assertEqual(
            core.intent_mismatches(fresh, [], date_fields=[(written, "20260915")]), [])

    def test_an_applied_set_filter_that_reverted_is_caught(self):
        written = flt(column="poNo", control="edtPo", dataset="dsFilterDVO")
        fresh = {"filters": [flt(column="poNo", control="edtPo",
                               dataset="dsFilterDVO", value="")], "unbound": []}
        problems = core.intent_mismatches(fresh, [], applied_filters=[(written, "PO123")])
        self.assertIn("PO123", problems[0])

    def test_an_unbound_filter_is_matched_by_control_name_not_dataset(self):
        written = flt(column="", control="edtLot", dataset="", bound=False)
        fresh = {"filters": [], "unbound": [flt(column="", control="edtLot",
                                              dataset="", bound=False, value="LOT1")]}
        self.assertEqual(
            core.intent_mismatches(fresh, [], applied_filters=[(written, "LOT1")]), [])
        problems = core.intent_mismatches(fresh, [], applied_filters=[(written, "LOT2")])
        self.assertIn("LOT2", problems[0])

    def test_division_that_reverted_is_caught(self):
        problems = core.intent_mismatches({"filters": [], "unbound": []}, [],
                                          division_wanted="VD", division_seen="MOBILE")
        self.assertIn("MOBILE", problems[0])
        self.assertIn("VD", problems[0])

    def test_division_matches_case_insensitively(self):
        self.assertEqual(
            core.intent_mismatches({"filters": [], "unbound": []}, [],
                                   division_wanted="vd", division_seen="VD"), [])

    def test_no_division_asked_for_is_never_checked(self):
        self.assertEqual(
            core.intent_mismatches({"filters": [], "unbound": []}, [],
                                   division_wanted=None, division_seen="MOBILE"), [])

    def test_two_instances_of_a_reusable_component_are_not_confused(self):
        # HISTORY.md - external review of 1957ba9/cff282b, finding #1: a
        # dataset+column pair is not always unique within one window - a
        # reusable component can appear twice, each instance carrying the
        # SAME dataset.column at a DIFFERENT path. Without path in the
        # match key, a fresh read of instance B could "confirm" a write
        # that was actually made to instance A.
        written = flt(column="paramDate", dataset="dsFilterDVO",
                      path="application.mainframe.winA_0_1.form.divInstanceA.form")
        # Instance A (the one actually written) still correctly shows what
        # was set; instance B, a completely different control that happens
        # to share the same dataset.column, shows something else entirely.
        instance_a = flt(column="paramDate", dataset="dsFilterDVO", value="20260915",
                         path="application.mainframe.winA_0_1.form.divInstanceA.form")
        instance_b = flt(column="paramDate", dataset="dsFilterDVO", value="99999999",
                         path="application.mainframe.winA_0_1.form.divInstanceB.form")
        fresh = {"filters": [instance_b, instance_a], "unbound": []}
        self.assertEqual(
            core.intent_mismatches(fresh, [], date_fields=[(written, "20260915")]), [],
            "instance A's own real value must be what gets checked, "
            "regardless of dict ordering")

        # Now invert the order - instance A first, B second - proving this
        # is not merely "whichever happens to come first survives".
        fresh_reversed = {"filters": [instance_a, instance_b], "unbound": []}
        self.assertEqual(
            core.intent_mismatches(fresh_reversed, [], date_fields=[(written, "20260915")]), [])


class FinalIntentVerificationIntegration(unittest.TestCase):
    """run_screen() actually wires intent_mismatches() into step 7.5 and
    refuses to click Inquiry when it finds a problem - proven here through
    the real orchestration, not just the pure function above."""

    class DriftingScreen:
        """A screen whose date field silently reverts the moment refresh()
        is called after Inquiry-adjacent steps finish - simulating a later
        step's oncolumnchanged handler undoing an earlier write, the exact
        scenario finding #4 describes."""

        def __init__(self):
            self.title, self.menu_id, self.win_id = "Drift", "M", "W"
            self.warnings = []
            self.last_tree = None
            self._written = flt(column="planYmd", control="mskPlan", dataset="dsFilterDVO")
            self._info = {"filters": [dict(self._written, value="20260915")],
                          "unbound": [], "grids": [grid("grdPlan", "dsPlan", 100)]}
            self.inquiry_called = False

        @property
        def info(self):
            return self._info

        @property
        def filters(self):
            return self._info["filters"]

        @property
        def unbound(self):
            return self._info.get("unbound", [])

        def grid(self, _preferred=None):
            return self._info["grids"][0]

        def set_option(self, wanted):
            raise AssertionError("no option was asked for in this test")

        def clear_stale(self, _keep):
            return []

        def set_date_range(self, from_value, to_value, profile=None):
            return [(self._written, from_value)]

        def refresh(self):
            # The revert: by the time step 7.5 re-reads the screen, the date
            # is back to empty - as if a later handler cleared it.
            self._info = {"filters": [dict(self._written, value="")],
                          "unbound": [], "grids": [grid("grdPlan", "dsPlan", 100)]}
            return self._info

        def options(self):
            return []

        def inquiry(self, _grid):
            self.inquiry_called = True
            return 999   # would be visibly wrong if this test ever saw it

    def test_a_field_that_reverted_between_writing_and_inquiry_stops_the_run(self):
        import gmes_profile
        screen = self.DriftingScreen()
        with patch.object(core, "open_screen", return_value=screen), \
             patch.object(core, "org_selection", return_value={"found": False}), \
             patch.object(gmes_profile, "load", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "no longer matches what was asked for"):
                core.run_screen(None, "P9999UM00", date_from="20260915", date_to="20260915",
                                verify="planYmd", export="none", log=lambda _m: None)
        self.assertFalse(screen.inquiry_called,
                         "Inquiry must never be clicked once a drift is detected")


class GeneratedJavaScript(unittest.TestCase):
    """The JS is built by % substitution, so a stray literal % or a
    miscounted placeholder is a runtime crash inside the browser call rather
    than an import error. Both are cheap to catch here."""

    def snippets(self):
        import gmes_data
        helpers = gmes_data.JS_HELPERS
        vis = "function(el){return true;}"
        return {
            "discover": core._js(core.JS_DISCOVER, helpers, vis, '"P1112UM00"',
                                 '["edt"]', '"btn"'),
            "left_options": core.JS_LEFT_OPTIONS,
            "org_trees": core._js(core.JS_ORG_TREES, helpers, '"P1112UM00"'),
            "alert_text": core._js(core.JS_ALERT_TEXT, helpers, '"P1112UM00"'),
            "tick_org": core._js(core.JS_TICK_ORG, helpers, '"ds"', '["VD"]',
                                 "true", '"OrgCategory_GDS"', "[]"),
            "control_value": core._js(core.JS_CONTROL_VALUE, '"an.id"'),
            "tab_close": core._js(core.JS_TAB_CLOSE_TARGET, vis, '"TAB_win_0_1"'),
            "org_selection": core._js(core.JS_ORG_SELECTION, vis),
            "data_read": gmes_data.js_read("P1112UM00", "dsFilterDVO", -1, 0),
            "data_read_at_path": gmes_data.js_read("P1112UM00", "dsFilterDVO", -1, 0,
                                                    path="application.mainframe.win_0_1.form"),
            "data_set_values": gmes_data.js_set_values("P1112UM00", "dsFilterDVO",
                                                        {"paramFromDate": "20260101"}, None),
            "data_set_values_at_path": gmes_data.js_set_values(
                "P1112UM00", "dsFilterDVO", {"paramFromDate": "20260101"}, None,
                path="application.mainframe.win_0_1.form"),
        }

    def test_every_template_formats(self):
        for name, js in self.snippets().items():
            self.assertNotIn("%s", js, f"{name} has an unfilled placeholder")

    def test_every_snippet_is_balanced_and_is_an_iife(self):
        for name, js in self.snippets().items():
            for opener, closer in (("{", "}"), ("(", ")"), ("[", "]")):
                self.assertEqual(js.count(opener), js.count(closer),
                                 f"{name} has unbalanced {opener}{closer}")
            self.assertTrue(js.strip().startswith("(function"), name)
            self.assertTrue(js.strip().endswith("})()"), name)


class DatasetInstanceIsolation(unittest.TestCase):
    """HISTORY.md - external review of 8ac502a, findings #1/#2/#3.

    `gmes_data._dataset(screenCode, dsName)` used to pick the FIRST live
    form matching a screen code, app-wide - and a screen code is not
    unique: `WidgetFilter.xfdl` (this file's own comment on it, in
    JS_DISCOVER) is a reusable component embedded on more than one screen.
    With two windows open at once, a write addressed by screen code +
    dataset name alone could land on a same-named dataset belonging to a
    DIFFERENT window than the one this run actually opened, while reporting
    success - the read-back that "proves" it re-resolves the exact same
    (wrong) instance and agrees with itself.

    The fix: JS_DISCOVER now carries the exact form PATH each filter/grid
    was found on (scoped to this run's own work window), and every write
    downstream is asked to resolve that exact path, never "whichever form
    matches first"."""

    def test_apply_passes_the_discovered_path_to_the_write(self):
        screen = core.Screen(ws="WS", code="P1112UM00",
                             opened={"menuId": "M", "winId": "W"}, info={})
        f = flt(column="paramFromDate", dataset="dsFilterDVO",
               path="application.mainframe.winA_0_1.form.divBasic.form")
        with patch.object(core.gmes_data, "set_filter",
                          return_value={"found": True, "applied": {"paramFromDate": "1"}}) as sf:
            screen.apply(f, "1")
        sf.assert_called_once()
        _, kwargs = sf.call_args
        self.assertEqual(kwargs["path"], f["path"])

    def test_a_filter_with_no_discovered_path_still_writes_with_path_none(self):
        # Older code paths (a hand-built dict, a profile ref) may carry no
        # "path" key at all - must fall back to the old whole-app search
        # rather than crashing on a missing key.
        screen = core.Screen(ws="WS", code="P1112UM00",
                             opened={"menuId": "M", "winId": "W"}, info={})
        f = flt(column="paramFromDate", dataset="dsFilterDVO")
        del f["path"]
        with patch.object(core.gmes_data, "set_filter",
                          return_value={"found": True, "applied": {"paramFromDate": "1"}}) as sf:
            screen.apply(f, "1")
        self.assertIsNone(sf.call_args.kwargs["path"])

    def test_grid_reads_and_verification_all_pass_the_discovered_path(self):
        screen = core.Screen(ws="WS", code="P1112UM00",
                             opened={"menuId": "M", "winId": "W"}, info={})
        g = grid("grdResult", "dsMasterProdPlan", 5000,
                path="application.mainframe.winA_0_1.form.divResult.form")
        found = {"found": True, "total": 1, "columns": ["planYmd"],
                "rows": [{"planYmd": "20260101"}]}
        with patch.object(core, "read_rows", return_value=found) as rr:
            screen.rows(g)
        self.assertEqual(rr.call_args.kwargs["path"], g["path"])

        with patch.object(core, "verify_rows", return_value=(["20260101"], None)) as vr:
            screen.verify_column(g, "planYmd", "20260101")
        self.assertEqual(vr.call_args.kwargs["path"], g["path"])

        with patch.object(core, "verify_date_range", return_value=(["20260101"], None)) as vd:
            screen.verify_date_range(g, "planYmd", "20260101", "20260101")
        self.assertEqual(vd.call_args.kwargs["path"], g["path"])

        with patch.object(core, "poll_inquiry", return_value=1) as pi:
            # poll_inquiry itself is mocked here; this only proves Screen.
            # inquiry() forwards the grid's path to it.
            screen.inquiry(g)
        self.assertEqual(pi.call_args.kwargs["path"], g["path"])

    def test_the_module_level_helpers_thread_path_down_to_gmes_data(self):
        with patch.object(core.gmes_data, "read_dataset",
                          return_value={"found": True, "total": 0, "rows": [],
                                       "columns": []}) as rd:
            core.read_rows("WS", "P1112WM00", "dsMasterProdPlan",
                           path="application.mainframe.winA_0_1.form")
        self.assertEqual(rd.call_args.kwargs["path"],
                         "application.mainframe.winA_0_1.form")

    def test_the_exact_path_reaches_the_generated_javascript_not_null(self):
        js_with_path = gmes_data.js_set_values(
            "P1112WM00", "dsFilterDVO", {"paramFromDate": "1"}, None,
            path="application.mainframe.winA_0_1.form")
        self.assertIn('"application.mainframe.winA_0_1.form"', js_with_path)

        js_without_path = gmes_data.js_set_values(
            "P1112WM00", "dsFilterDVO", {"paramFromDate": "1"}, None)
        # The third argument to _dataset() must be JSON `null`, not the
        # string "None" - a Python str(None) leak here would silently ask
        # the browser to match forms whose path literally reads "None".
        self.assertIn("_dataset(", js_without_path)
        self.assertNotIn('"None"', js_without_path)

    def test_the_write_refuses_a_multi_row_dataset_with_no_valid_row_position(self):
        # Source-level guard, mirroring how LockoutWarningDetection tests
        # the real regex rather than a re-typed copy: this dataset is not
        # executable offline (no mock for G-MES, CLAUDE.md 4.3), so the
        # JS source itself is asserted to contain the refusal rather than
        # a Python re-implementation that could silently drift from it.
        js = gmes_data.js_set_values("P1112WM00", "dsFilterDVO",
                                     {"paramFromDate": "1"}, None)
        self.assertIn("rowposition", js)
        self.assertIn("refusing to guess which row is the filter", js)

    def test_a_single_row_dataset_needs_no_row_position_at_all(self):
        js = gmes_data.js_set_values("P1112WM00", "dsFilterDVO",
                                     {"paramFromDate": "1"}, None)
        self.assertIn("count === 1", js)

    def test_discovery_dedup_is_scoped_by_path_not_dataset_column_alone(self):
        # HISTORY.md - external review of 1957ba9/cff282b, finding #2:
        # JS_DISCOVER used to collapse every filter sharing one
        # dataset.column into a single entry BEFORE path ever reached
        # Python - two genuinely different instances of a reusable
        # component would silently become one, discarding whichever lost
        # the dedup regardless of how carefully the write/verify path
        # matches by path afterward. Source-level (not executable offline,
        # CLAUDE.md 4.3), the same way the ancestor-walk fix above is.
        self.assertIn("f.path + '|' + f.dataset + '.' + f.column", core.JS_DISCOVER)

    def test_bound_vs_unbound_cross_check_is_keyed_by_dom_id_not_path(self):
        # HISTORY.md Phase 82.7, live-caught on M3912UM00: a bind's own
        # `path` is the form that owns the DATASET, not the form actually
        # containing a deeply-nested control (fromDate/searchTypeCode/...
        # live several Divs below the form that binds them). Keying the
        # bound/unbound cross-check by `path + control` (this file's own
        # earlier fix, for the UNRELATED problem the dedup above handles)
        # broke it here: all 7 real filters were reported a second time as
        # unbound. `id` - the fully expanded DOM id, computed identically
        # by both loops for the same physical element regardless of which
        # form reports it - replaced it.
        self.assertIn("boundLeaves[f.id] = true", core.JS_DISCOVER)
        self.assertIn("boundLeaves[u.id] || seenUnbound[u.id]", core.JS_DISCOVER)

    def test_input_detection_prefers_the_live_component_type_over_a_name_guess(self):
        # HISTORY.md Phase 82.7, live-caught on M3912UM00: its filter panel
        # binds fromDate/toDate/searchTypeCode/searchStartNo/
        # searchModelCode/searchUse/searchProductCode - none of which start
        # with any of INPUT_PREFIXES (edt/msk/cbo/chk/rdo/cal/spn/txt/lst),
        # so kindOf()'s name-prefix guess dropped every one of the screen's
        # 7 real filters, reporting "Filters bound to a dataset (0)" on a
        # screen with a visible Period/Type/Product/Start No./Model panel.
        # Confirmed live: the resolved elements' actual Nexacro types were
        # MaskEdit, Combo and Edit - authored by the platform, not a
        # person, and not a guess. Source-level (CLAUDE.md 4.3).
        self.assertIn("INPUT_KIND_RE = /^(edit|maskedit|combo|checkbox|radio|"
                      "spin|calendar|listbox|textarea)$/i", core.JS_DISCOVER)
        # The function's actual BODY must consult the live kind first, not
        # merely have the regex defined somewhere nearby unused - checked
        # by sabotaging exactly this line and confirming the test above
        # fails without it.
        self.assertIn("if (kind) return INPUT_KIND_RE.test(kind);", core.JS_DISCOVER)
        # The element (and therefore its real `kind`) must be resolved
        # BEFORE the input/display decision - checking the guess first
        # would defeat the whole point.
        bound_section = core.JS_DISCOVER[core.JS_DISCOVER.index("Bound controls -> settable"):]
        el_at = bound_section.index("const el = id ? document.getElementById(id) : null;")
        decision_at = bound_section.index("if (!isInputControl(kind, leaf)) continue;")
        self.assertLess(el_at, decision_at)

    def test_shell_form_filter_also_excludes_the_left_panel_widget_filter(self):
        # HISTORY.md Phase 82.12, live-caught on P3151WM00: the comment
        # right above SHELL already claimed "the widget list" was excluded,
        # but the regex itself never named WidgetFilter.xfdl.js - live, its
        # own grid (Grid02/dsGrid00) passed the filename test and was then
        # offered as a candidate result grid, even though a read against it
        # returns nothing (it belongs to the left filter panel every G-MES
        # screen carries, not to the report). Checked as the literal regex
        # fragment, not a bare substring - the comment explaining this fix
        # also says "WidgetFilter", which would let a sabotage that removed
        # only the pattern slip past a looser check.
        self.assertIn("PortalMain|WidgetFilter/i", core.JS_DISCOVER)

    def test_a_widget_nested_inside_the_left_filter_panel_is_excluded_by_path(self):
        # HISTORY.md Phase 82.12, live-caught on P3151WM00: a date-range
        # calendar picker embedded INSIDE the left filter panel ships as its
        # own file, CalendarD.xfdl.js - not shell by name, and its dataset
        # (dsCalendar) is shaped like neither an org tree nor a Quick View,
        # so neither existing chrome check caught it. Live, it was the only
        # grid with a non-zero bounding box while the screen's real result
        # grids all read area 0 (their tab was not yet active), so it won
        # choose_grid()'s "biggest" default outright. The path segment
        # 'divFilter.divWidgetMain' is specific to the LEFT panel's own
        # widget container - the work area's is named 'divWork.divWidgetMain'
        # (confirmed live) - so this cannot also exclude a real result grid.
        grids_section = core.JS_DISCOVER[core.JS_DISCOVER.index("Grids -> candidate result sets"):]
        self.assertIn("h.path.indexOf('divFilter.divWidgetMain') !== -1", grids_section)
        # Must run AFTER chromeDatasets/__EXCEL__ are checked but BEFORE the
        # grid is actually pushed, or a chrome widget still gets offered.
        exclude_at = grids_section.index("h.path.indexOf('divFilter.divWidgetMain') !== -1")
        push_at = grids_section.index("grids.push(")
        self.assertLess(exclude_at, push_at)

    def test_form_walk_follows_a_tab_controls_own_tabpages_collection(self):
        # HISTORY.md Phase 82.11, live-caught on P3151WM00: a Nexacro Tab
        # control has no .form/.components of its own at all - its pages
        # (Tabpage1..N) are reachable only through a SEPARATE .tabpages
        # collection. Without walking it, every grid/filter/dataset living
        # inside a tabbed panel was invisible to _findForms() - the
        # foundational walker essentially every discovery/read/write path in
        # this project depends on. Source-level (CLAUDE.md 4.3): no mock for
        # a live Nexacro Tab object exists to exercise this offline.
        self.assertIn("tabpages = c && c.tabpages", gmes_data.JS_HELPERS)
        self.assertIn("walkForm(pageForm,", gmes_data.JS_HELPERS)

    def test_form_walk_depth_cap_allows_for_tabbed_nesting(self):
        # HISTORY.md Phase 82.11, live-caught on P3151WM00: the pre-existing
        # depth > 12 cap was tuned for a form tree with no tabbed panels.
        # Walking into a Tab's own pages adds 2-3 levels per nested tab, so
        # the screen's actually-visible tab's own result grid (grdMain01)
        # sat just past the old cap while a DIFFERENT, hidden tab's grid was
        # still found - a more misleading failure than finding nothing at
        # all. Asserted as "wide enough for real nested-tab layouts", not
        # pinned to the exact number, so a future generous-headroom bump
        # does not fail this test for the wrong reason.
        m = re.search(r"depth > (\d+)", gmes_data.JS_HELPERS)
        self.assertIsNotNone(m, "walkForm's depth cap must still exist")
        self.assertGreaterEqual(int(m.group(1)), 20)

    def test_the_exact_path_search_also_walks_ancestor_forms(self):
        # HISTORY.md Phase 80.4, live-caught: P1111UM00's grdSum grid's own
        # component path is ...divWork.divLeft, but Nexacro resolves
        # dsModelPlanList through the ANCESTOR SCOPE CHAIN - it is only an
        # own property of the PARENT form, ...divWork. Matching the exact
        # path alone (this test's own earlier version, before the live
        # fix) made every read/write on that screen fail closed. Asserted
        # at the source level, the same way LockoutWarningDetection tests
        # the real regex rather than a re-typed copy - this cannot run
        # offline (no mock for G-MES, CLAUDE.md 4.3).
        js = gmes_data.js_set_values("P1112WM00", "dsFilterDVO",
                                     {"paramFromDate": "1"}, None,
                                     path="a.b.c")
        self.assertIn("h.path === exactPath", js)
        self.assertIn("exactPath.indexOf(h.path + '.') === 0", js)
        # Closest scope wins first - sorted longest path (most specific)
        # first, so an exact match is always preferred over an ancestor
        # when both happen to carry a same-named dataset.
        self.assertIn("b.path.length - a.path.length", js)

    def test_ancestor_matching_never_crosses_into_a_different_window(self):
        # The safety property the exact-path fix exists for must survive
        # widening it to ancestors: reproduced here in plain Python against
        # the exact same rule the JS above implements, since a sibling
        # window's path can never be a prefix of this one's - they diverge
        # at the win*_N_NNN segment itself.
        def is_ancestor_or_self(candidate, exact_path):
            return candidate == exact_path or exact_path.startswith(candidate + ".")

        window_a = "application.mainframe.workFrameSet.winPPM0219_0_1.divWork"
        window_b_sibling = "application.mainframe.workFrameSet.winPPM0219_0_2.divWork"
        self.assertFalse(is_ancestor_or_self(window_b_sibling, window_a))
        # But a genuine ancestor of the SAME window still matches.
        ancestor = "application.mainframe.workFrameSet.winPPM0219_0_1"
        self.assertTrue(is_ancestor_or_self(ancestor, window_a))


class FindRefStablePathMatching(unittest.TestCase):
    """HISTORY.md - external review of 1957ba9/cff282b, finding #3: a saved
    profile's `from`/`to`/`grid` reference used to keep only dataset+column
    (or control name), matched against WHATEVER live control has that name
    on replay - the exact ambiguity Phase 80 closed for a fresh discovery,
    reopened specifically for replay mode. `stable_path` (the relative path
    with the window's own renumbered instance segment stripped, the same
    trick Phase 76 already uses for option identity) closes it without
    breaking every profile written before this fix."""

    def make_screen(self, filters=(), unbound=()):
        return core.Screen(ws=None, code="P1112UM00",
                           opened={"menuId": "M", "winId": "W"},
                           info={"filters": list(filters), "unbound": list(unbound)})

    def test_a_ref_with_no_stable_path_matches_by_dataset_and_column_as_before(self):
        # Every profile written before this fix - must keep working exactly
        # as it always did, with no relearn forced on anyone.
        ref = {"dataset": "dsFilterDVO", "column": "paramFromDate",
              "control": "mskDateFrom", "form": "", "label": ""}
        current = flt(column="paramFromDate", dataset="dsFilterDVO",
                      path="application.mainframe.winA_0_1.form.divOnly.form")
        screen = self.make_screen(filters=[current])
        self.assertIs(screen.find_ref(ref), current)

    def test_a_ref_with_a_stable_path_only_matches_that_exact_instance(self):
        ref = {"dataset": "dsFilterDVO", "column": "paramDate", "control": "",
              "form": "", "label": "",
              "stable_path": "form.divInstanceA.form"}
        instance_a = flt(column="paramDate", dataset="dsFilterDVO",
                         path="application.mainframe.winA_0_1.form.divInstanceA.form",
                         value="right one")
        instance_b = flt(column="paramDate", dataset="dsFilterDVO",
                         path="application.mainframe.winA_0_1.form.divInstanceB.form",
                         value="wrong one")
        screen = self.make_screen(filters=[instance_b, instance_a])
        found = screen.find_ref(ref)
        self.assertIs(found, instance_a)
        self.assertEqual(found["value"], "right one")

    def test_a_stable_path_that_no_longer_exists_is_gone_not_a_loose_match(self):
        # The reusable component's shape changed - a dataset.column match
        # exists, but not at the path this profile actually proved. That is
        # evidence worth stopping on (CLAUDE.md 3.9), not a "close enough".
        ref = {"dataset": "dsFilterDVO", "column": "paramDate", "control": "",
              "form": "", "label": "",
              "stable_path": "form.divInstanceA.form"}
        only_b = flt(column="paramDate", dataset="dsFilterDVO",
                     path="application.mainframe.winA_0_1.form.divInstanceB.form")
        screen = self.make_screen(filters=[only_b])
        self.assertIsNone(screen.find_ref(ref))


class OrgTreeWindowScoping(unittest.TestCase):
    """HISTORY.md - external review of 1957ba9/cff282b, finding #5:
    `tick_org()`'s own fallback search matches by the TREE's shared form
    name (e.g. "OrgCategory_GDS"), never the work screen's own code - it is
    a reusable component embedded on many unrelated screens, so an
    unscoped search can reach a completely different window's copy of the
    same tree and silently tick a division nobody asked to change there.
    `paths` - the exact instances `Screen.trees()` already found within
    THIS run's own window - is what actually restricts the write."""

    def test_the_generated_js_is_scoped_by_paths_when_given(self):
        # Source-level (not executable offline, CLAUDE.md 4.3), the same
        # way the ancestor-walk and dedup fixes above are.
        js = core._js(core.JS_TICK_ORG, gmes_data.JS_HELPERS, '"ds"', '["VD"]',
                      "true", '"OrgCategory_GDS"', '["a.b.c"]')
        self.assertIn("paths.indexOf(h.path) >= 0", js)
        self.assertIn("paths && paths.length", js)

    def make_screen(self, trees):
        screen = core.Screen(ws=Mock(), code="P1112UM00",
                             opened={"menuId": "M", "winId": "winA_0_1"}, info={})
        self._trees_patcher = patch.object(core, "org_trees",
                                           return_value={"trees": trees})
        self._trees_patcher.start()
        self.addCleanup(self._trees_patcher.stop)
        return screen

    def test_select_org_passes_every_window_scoped_copy_of_the_same_tree(self):
        # Two copies of the SAME logical tree in THIS window (the Work
        # Calendar three-tabs case Phase 65's own comment describes) -
        # both paths must be passed through.
        copy1 = {"form": "OrgCategory_GDS", "dataset": "dsCatCommonTreeNodeDVO",
                 "names": ["VD"], "settable": True,
                 "path": "application.mainframe.winA_0_1.form.divTab1"}
        copy2 = {"form": "OrgCategory_GDS", "dataset": "dsCatCommonTreeNodeDVO",
                 "names": ["VD"], "settable": True,
                 "path": "application.mainframe.winA_0_1.form.divTab2"}
        screen = self.make_screen([copy1, copy2])
        with patch.object(core, "tick_org",
                          return_value={"found": True, "ticked": [], "cleared": []}) as tick, \
             patch.object(core, "org_selection",
                          return_value={"found": True, "org": "VD"}):
            # tree= picks a target among the two pool-equivalent copies
            # without tripping the pre-existing (unrelated) ambiguity
            # refusal - this test is about paths gathering, not pool choice.
            screen.select_org("VD", tree="OrgCategory_GDS")
        self.assertEqual(sorted(tick.call_args.kwargs["paths"]),
                         sorted([copy1["path"], copy2["path"]]))

    def test_an_unrelated_tree_elsewhere_in_the_window_is_not_included(self):
        target = {"form": "OrgCategory_GDS", "dataset": "dsCatCommonTreeNodeDVO",
                 "names": ["VD"], "settable": True,
                 "path": "application.mainframe.winA_0_1.form.divOrg"}
        unrelated = {"form": "OtherTree", "dataset": "dsOtherDVO",
                    "names": ["MOBILE"], "settable": True,
                    "path": "application.mainframe.winA_0_1.form.divOther"}
        screen = self.make_screen([target, unrelated])
        with patch.object(core, "tick_org",
                          return_value={"found": True, "ticked": [], "cleared": []}) as tick, \
             patch.object(core, "org_selection",
                          return_value={"found": True, "org": "VD"}):
            screen.select_org("VD")
        self.assertEqual(tick.call_args.kwargs["paths"], [target["path"]])


class DailyProdPlanPathResolution(unittest.TestCase):
    """`gmes_daily_prodplan.py` addresses its datasets by hardcoded screen
    code + dataset name (HISTORY.md Phase 78's own comment: it deliberately
    shares gmes_core's dataset-level functions rather than reimplementing
    them). `path_for()` closes the same gap `Screen.apply()` was fixed for,
    using the `Screen` object `ensure_screen()` now returns instead of
    throwing it away as a formatted string."""

    def make_screen(self, filters=(), unbound=(), grids=()):
        info = {"filters": list(filters), "unbound": list(unbound),
                "grids": list(grids)}
        return core.Screen(ws=None, code="P1112UM00",
                           opened={"menuId": "M", "winId": "W"}, info=info)

    def test_resolves_a_bound_filter_by_dataset_name(self):
        import gmes_daily_prodplan as job
        f = flt(dataset="dsFilterDVO",
               path="application.mainframe.winA_0_1.form.divBasic.form")
        screen = self.make_screen(filters=[f])
        self.assertEqual(job.path_for(screen, "dsFilterDVO"), f["path"])

    def test_resolves_a_result_grid_by_dataset_name(self):
        import gmes_daily_prodplan as job
        g = grid("grdResult", "dsMasterProdPlan", 5000,
                path="application.mainframe.winA_0_1.form.divResult.form")
        screen = self.make_screen(grids=[g])
        self.assertEqual(job.path_for(screen, "dsMasterProdPlan"), g["path"])

    def test_an_undiscovered_dataset_resolves_to_none_not_a_crash(self):
        import gmes_daily_prodplan as job
        screen = self.make_screen()
        self.assertIsNone(job.path_for(screen, "dsSomethingElse"))

    def test_select_division_only_forwards_paths_for_its_own_org_tree(self):
        # HISTORY.md - external review of 1957ba9/cff282b, finding #5,
        # applied to the nightly job specifically: ORG_SCREEN
        # ("OrgCategory_GDS") is the tree's shared form name, not this
        # job's own work screen code. select_division() must gather ITS
        # OWN tree's paths from screen.trees() (window-scoped, since
        # org_trees() anchors on screen.code) and pass them to
        # core.tick_org() - not let tick_org() fall back to its unscoped
        # app-wide search, and not include some OTHER dataset's paths that
        # happen to also be discovered in the same window.
        import gmes_daily_prodplan as job
        screen = self.make_screen()
        own_tree = {"form": job.ORG_SCREEN, "dataset": job.ORG_TREE_DATASET,
                   "names": ["VD"], "settable": True,
                   "path": "application.mainframe.winA_0_1.form.divOrg"}
        unrelated_tree = {"form": "OtherTree", "dataset": "dsOtherDVO",
                         "names": ["VD"], "settable": True,
                         "path": "application.mainframe.winA_0_1.form.divOther"}
        with patch.object(core, "org_trees",
                          return_value={"trees": [own_tree, unrelated_tree]}), \
             patch.object(job.core, "tick_org",
                          return_value={"found": True, "ticked": [], "cleared": []}) as tick, \
             patch.object(job.core, "org_selection",
                          return_value={"found": True, "org": "VD"}):
            job.select_division(Mock(), screen, "VD")
        self.assertEqual(tick.call_args.kwargs["paths"], [own_tree["path"]])

    def test_ensure_screen_returns_the_live_screen_not_a_formatted_string(self):
        import gmes_daily_prodplan as job
        opened_screen = core.Screen(ws="WS", code=job.CONTAINER_SCREEN,
                                    opened={"menuId": "M", "winId": "W"},
                                    info={"filters": [], "unbound": [], "grids": []})
        opened_screen.refresh = lambda: opened_screen.info
        with patch.object(job.core, "open_screen", return_value=opened_screen), \
             patch.object(job.gmes_data, "list_forms",
                          return_value={"forms": [{"file": "P1112WM00.xfdl.js"}]}):
            result = job.ensure_screen("WS")
        self.assertIs(result, opened_screen)

    def test_main_resolves_and_forwards_paths_end_to_end(self):
        # Sabotage-provable: removing `path=filter_path`/`path=result_path`
        # from main()'s calls makes this test's mocks receive `path=None`
        # instead of the fixture's real path and fail.
        import gmes_daily_prodplan as job
        filter_entry = flt(dataset="dsFilterDVO",
                          path="application.mainframe.winA_0_1.form.divBasic.form")
        grid_entry = grid("grdResult", job.RESULT_DATASET, 5000,
                         path="application.mainframe.winA_0_1.form.divResult.form")
        opened_screen = self.make_screen(filters=[filter_entry], grids=[grid_entry])
        opened_screen.title, opened_screen.win_id = "Production Plan", "winA_0_1"

        with patch.object(sys, "argv", ["gmes_daily_prodplan.py"]), \
             patch.object(job.core, "acquire_run_lock"), \
             patch.object(job.core, "release_run_lock"), \
             patch.object(job.core, "sign_in", return_value=True), \
             patch.object(job, "connect_gmes", return_value=Mock(close=lambda: None)), \
             patch.object(job, "is_logged_in", return_value=(True, "someone")), \
             patch.object(job, "ensure_screen", return_value=opened_screen), \
             patch.object(job, "set_plan_date", return_value="ok") as spd, \
             patch.object(job, "select_division", return_value="ok"), \
             patch.object(job, "run_inquiry", return_value=5) as ri, \
             patch.object(job, "verify_result_date", return_value=["20260101"]) as vrd, \
             patch.object(job, "download_excel", return_value="/tmp/x.xlsx"), \
             patch.object(job.core, "check_download"), \
             patch.object(job, "is_drm_protected", return_value=False), \
             patch.object(job.os.path, "getsize", return_value=1024), \
             patch.object(job, "export_clean_data", return_value=("/tmp/x.csv", 1, 0)) as ecd, \
             patch.object(job.shutil, "move"), \
             patch.object(job.os, "makedirs"):
            code = job.main()

        self.assertEqual(code, 0)
        self.assertEqual(spd.call_args.kwargs["path"], filter_entry["path"])
        self.assertEqual(ri.call_args.kwargs["path"], grid_entry["path"])
        self.assertEqual(vrd.call_args.kwargs["path"], grid_entry["path"])
        self.assertEqual(ecd.call_args.kwargs["path"], grid_entry["path"])

    def test_main_refuses_rather_than_fall_back_to_an_unscoped_search(self):
        # HISTORY.md - external review of 1957ba9/cff282b, finding #6: this
        # job knows exactly which two datasets it needs: a missing path for
        # either means the screen is not in the state this job assumes, and
        # that must stop the run, not silently retry the old whole-app
        # search gmes_data.py falls back to when path=None.
        import gmes_daily_prodplan as job
        # No filters/grids discovered at all - path_for() resolves both to
        # None.
        opened_screen = self.make_screen()
        opened_screen.title, opened_screen.win_id = "Production Plan", "winA_0_1"

        with patch.object(sys, "argv", ["gmes_daily_prodplan.py"]), \
             patch.object(job.core, "acquire_run_lock"), \
             patch.object(job.core, "release_run_lock"), \
             patch.object(job.core, "sign_in", return_value=True), \
             patch.object(job, "connect_gmes", return_value=Mock(close=lambda: None)), \
             patch.object(job, "is_logged_in", return_value=(True, "someone")), \
             patch.object(job, "ensure_screen", return_value=opened_screen), \
             patch.object(job, "set_plan_date") as spd, \
             patch.object(job, "screenshot_on_failure"):
            code = job.main()

        self.assertEqual(code, 1)
        spd.assert_not_called()   # stopped before writing anything


class RunLock(unittest.TestCase):
    """Open Item #17, live-proven: two gmes_report.py runs sharing one
    Chrome/CDP session interfere with each other. A concurrent run against
    P1112UM00 failed with "The result row could not be clicked (grid row
    not visible)" while another run had M4131UM00 open in the same
    browser - a real symptom that gives no hint a second run is the cause.
    acquire_run_lock()/release_run_lock() turn that into an immediate,
    explicit refusal."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="gmes-lock-test-")
        self.lock_path = os.path.join(self.tmp, ".run.lock")
        self.patcher = patch.object(core, "RUN_LOCK_PATH", self.lock_path)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(core.release_run_lock)

    def test_first_caller_gets_the_lock(self):
        self.assertTrue(core.acquire_run_lock())
        self.assertTrue(os.path.exists(self.lock_path))

    def test_second_caller_is_refused_while_the_first_still_holds_it(self):
        core.acquire_run_lock()
        with self.assertRaises(core.RunLocked) as cm:
            core.acquire_run_lock()
        self.assertIn(str(os.getpid()), str(cm.exception))

    def test_release_lets_the_next_caller_in(self):
        core.acquire_run_lock()
        core.release_run_lock()
        self.assertTrue(core.acquire_run_lock())

    def test_a_lock_left_by_a_dead_process_does_not_block_forever(self):
        # A pid that cannot possibly be a live process on this machine -
        # simulates a run that crashed before it could release its lock.
        with open(self.lock_path, "w", encoding="utf-8") as fh:
            fh.write("999999999 2020-01-01 00:00:00\n")
        self.assertTrue(core.acquire_run_lock())

    def test_releasing_an_unheld_lock_does_not_raise(self):
        core.release_run_lock()  # no lock file exists yet


if __name__ == "__main__":
    unittest.main(verbosity=2)
