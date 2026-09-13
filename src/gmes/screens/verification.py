"""Reading back result rows, confirming they carry what was asked for, and
waiting for an Inquiry to actually settle.

Forked from gmes_core.py.
"""
import time

from ..nexacro.dom import click_control
from ..nexacro.popups import find_child_popups
from ..query.dataset_reader import read_dataset
from .grids import digits_only


def read_rows(ws, form_code, dataset, limit=-1):
    return read_dataset(ws, form_code, dataset, limit=limit)


def verify_rows(ws, form_code, dataset, column, expected, sample=None):
    """Confirm the returned rows carry the value that was asked for.

    A stale result set looks exactly like a fresh one, and an export of the
    wrong day is worse than no export. Digits are compared rather than text,
    so 2026-09-08 and 20260908 are the same answer.

    Returns (values_seen, problem). `problem` is None when the result agrees;
    the caller decides whether a disagreement is fatal."""
    # A sample can contain one good row while the export contains thousands
    # of bad ones.  Read the same complete, paged dataset that is exported.
    result = read_rows(ws, form_code, dataset, limit=-1)
    if not result.get("found"):
        return None, "the result dataset disappeared before verification"
    if not result["rows"]:
        return None, "the result dataset contains no rows to verify"
    if column not in result["columns"]:
        near = [c for c in result["columns"] if column.lower() in c.lower()]
        return None, (f"the result has no {column!r} column"
                      + (f" - did you mean {near[:4]}?" if near else ""))
    expected_text = str(expected or "").strip()
    if not expected_text:
        return None, "verification needs an expected value"
    numeric = bool(digits_only(expected_text))
    values = [str(row.get(column) or "").strip() for row in result["rows"]]
    seen = sorted({digits_only(v) if numeric else v.casefold() for v in values if v})
    want = digits_only(expected_text) if numeric else expected_text.casefold()
    if not seen:
        return [], f"the results contain no values in {column!r}"
    wrong = [value for value in seen if value != want]
    if wrong:
        return seen, (f"the results carry {column}={seen}, not exactly the "
                      f"requested {expected_text}")
    return seen, None


def poll_inquiry(ws, form_code, dataset, max_wait=300, settle_checks=4,
                 poll_interval=1.0):
    """Click Inquiry and wait for THIS screen's result set to settle.

    Polling a dataset by a hardcoded name reported 875 rows - the count still
    sitting in the PREVIOUS screen's dataset - for a screen that had returned
    17. The export was right because it used the discovered dataset; only the
    number and the wait were wrong, which is the more dangerous combination:
    the file is correct, the log lies, and nobody checks.

    An empty result set does not mean the query finished either. Nexacro
    clears the dataset the instant Inquiry is pressed and refills it when the
    server answers, so the count sits at 0 for the whole round trip. Treating
    stable zeros as settled reported 0 rows and refused to export while 790
    rows were on their way.

    So: settle only on a count above zero that has stopped moving, and require
    the count to have been seen CHANGING, so a dataset left populated by an
    earlier run is not mistaken for a finished query. Neither cap is an
    estimate of how long the query takes - the loop exits the moment it has
    its answer, which is what makes a generous cap free."""
    def row_count():
        r = read_rows(ws, form_code, dataset, limit=0)
        return r.get("total", -1) if r.get("found") else -1

    before = row_count()
    button = click_control(ws, cls="btn_LF_Search_New", text="Inquiry")
    if not button:
        raise RuntimeError("the Inquiry button was not found on this screen")

    started = time.time()
    last, stable, changed = None, 0, False

    while time.time() - started < max_wait:
        time.sleep(poll_interval)
        count = row_count()

        # An alert instead of results - usually "no data found".
        popups = find_child_popups(ws)
        if popups.get("count"):
            names = [p["name"] for p in popups["popups"]]
            raise RuntimeError(f"a dialog opened instead of results: {names}")

        if count != before:
            changed = True

        if count > 0:
            stable = stable + 1 if count == last else 0
            last = count
            if stable >= settle_checks and changed:
                return count
        else:
            last, stable = count, 0
            # A genuinely empty answer is handled by the caller as a failure.
            # Do not invent completion from a quiet old dataset.

    raise RuntimeError(f"the query had not settled after {max_wait}s "
                       f"(last count {last})")
