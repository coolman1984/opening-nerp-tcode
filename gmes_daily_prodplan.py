"""
Nightly job: Production Plan by Order(Line), Division VD, yesterday's plan
date, exported with GMES's own Excel download.

    python gmes_daily_prodplan.py                  # yesterday (the normal run)
    python gmes_daily_prodplan.py --date 20260908  # a specific plan date
    python gmes_daily_prodplan.py --days-back 2
    python gmes_daily_prodplan.py --keep-open      # leave Chrome up afterwards

Result: "Data Hub Folder/GMES/Production Plan by Order(Line)_<date>_<time>.xlsx"

Screen: PPM > Production Plan > Prod. Plan Inquiry > Detail Schedule >
Production Plan by Order(Line)  [ P1112UM00 > P1112WM00 ], filter panel
P1112WF00, org tree OrgCategory_GDS.

Runs with nobody watching, so every step verifies rather than assumes, and
exits non-zero with a screenshot if anything is off.
"""
import argparse
import os
import shutil
import sys
import time
from datetime import datetime, timedelta

import cdp_common
import gmes_core as core
import gmes_data
from gmes_common import connect_gmes, is_logged_in

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = core.OUTPUT_DIR
REPORT_NAME = "Production Plan by Order(Line)"

# Screen codes from the breadcrumb - stable, unlike the window ids.
CONTAINER_SCREEN = "P1112UM00"   # what the search bar opens
FILTER_SCREEN = "P1112WF00"      # left panel: dates, and the Inquiry it feeds
RESULT_SCREEN = "P1112WM00"      # the grid's data
ORG_SCREEN = "OrgCategory_GDS"   # the Org tab's tree

RESULT_DATASET = "dsMasterProdPlan"
ORG_TREE_DATASET = "dsCatCommonTreeNodeDVO"

EXCEL_BTN = core.EXCEL_BTN


# ---------------------------------------------------------------------------
# Steps
#
# Each one is a thin wrapper over gmes_core, so this job and the generic
# runner share one implementation. They did not always: a second copy of the
# inquiry wait is how a run came to report the previous screen's row count.
# What stays here is only what is specific to THIS report - which screen,
# which datasets, and which rows are subtotals.
# ---------------------------------------------------------------------------

def ensure_screen(ws, screen_code=CONTAINER_SCREEN, max_wait=90):
    """Make sure the report's screen is open, in front, and finished building.

    Without this the job silently depended on that screen happening to be the
    session's default. It is reached by screen code, the same one entry point
    that reaches all 809 screens, rather than by walking four levels of menu.

    Being open is not enough - it must be the tab in FRONT. A background
    screen still accepts dataset writes, so the filters applied correctly and
    the Inquiry click then landed on whichever screen was actually visible,
    returning zero rows from the wrong report."""
    screen = core.open_screen(ws, screen_code, ready_wait=max_wait)

    # This report reads P1112WM00, which is a different form from the one the
    # search box opens. Confirm it exists rather than assuming the container
    # brought it with it.
    deadline = time.time() + max_wait
    while time.time() < deadline:
        forms = gmes_data.list_forms(ws)["forms"]
        if any((f["file"] or "").startswith(RESULT_SCREEN) for f in forms):
            return f"{screen.title} ({screen.win_id})"
        time.sleep(1.0)
    raise RuntimeError(f"{screen_code} opened but {RESULT_SCREEN} never appeared.")


def set_plan_date(ws, yyyymmdd):
    """Write the plan-date range into the filter panel's dataset.

    Setting the Dataset rather than typing into the date box: Nexacro binds
    the two, so the visible field updates, and there is no calendar widget
    to fight with."""
    result = gmes_data.set_filter(ws, FILTER_SCREEN, "dsFilterDVO",
                                 {"paramFromDate": yyyymmdd, "paramEndDate": yyyymmdd})
    if not result.get("found"):
        raise RuntimeError(
            f"The filter panel ({FILTER_SCREEN}) is not open. Is "
            "'Production Plan by Order(Line)' the active screen?")
    applied = result.get("applied", {})
    if applied.get("paramFromDate") != yyyymmdd or applied.get("paramEndDate") != yyyymmdd:
        raise RuntimeError(f"The plan date did not take: {applied}")
    return applied


def select_division(ws, name="VD"):
    """Tick a division in the Org tree.

    Without this the query returns nothing at all and the screen just says
    "Select Search Criteria" - the single most likely reason for a silent
    empty export, so it is checked rather than assumed.

    The row is found by its visible name, not by row number: the tree is built
    from the user's permissions and its order is not guaranteed. Ticks this
    run did not ask for are cleared, because a tick survives between runs
    exactly as a typed filter does."""
    result = core.tick_org(ws, ORG_SCREEN, ORG_TREE_DATASET, [name], exclusive=True)
    if not result.get("found"):
        raise RuntimeError(
            f"Division {name!r} was not in the Org tree "
            f"({result.get('reason', 'not present')}). "
            f"Divisions present: {result.get('available', '(tree not loaded)')}")
    return result


def run_inquiry(ws, **kwargs):
    """Click Inquiry and wait until this report's result set has settled."""
    return core.poll_inquiry(ws, RESULT_SCREEN, RESULT_DATASET, **kwargs)


def verify_result_date(ws, expected_yyyymmdd):
    """Confirm the rows really are for the date we asked for.

    A stale result set from a previous query looks exactly like a fresh one,
    and an export of the wrong day is worse than no export at all - so a
    mismatch stops the job here rather than producing a plausible file."""
    dates, problem = core.verify_rows(ws, RESULT_SCREEN, RESULT_DATASET,
                                      "planYmd", expected_yyyymmdd, sample=5)
    if problem:
        raise RuntimeError(problem + ". Refusing to export the wrong day.")
    return dates


def download_excel(ws, target_dir, timeout=240):
    """Click the toolbar Excel icon, confirm its dialog, wait for the file."""
    return core.download_excel(ws, target_dir, timeout=timeout)


def deliver(downloaded_path, target_dir, stamp):
    """Move the export to its final name."""
    os.makedirs(target_dir, exist_ok=True)
    final = os.path.join(target_dir, f"{REPORT_NAME}_{stamp}.xlsx")
    if os.path.abspath(downloaded_path) != os.path.abspath(final):
        shutil.move(downloaded_path, final)
    return final


is_drm_protected = core.is_drm_protected


def export_clean_data(ws, target_dir, stamp, plan_date):
    """Write a machine-readable copy straight from the Dataset.

    Two reasons this exists alongside the official download:
      * The GMES file is DRM-encrypted, so nothing downstream can read it.
      * The Dataset carries rows with no PO and no master line that the grid
        renders as LINE SUM and PROC SUM: the labels are added by the grid at
        render time and are not stored, which is why they read as blank.
        Exporting them raw would inflate the row count - 875 against the
        screen's own 790 - so they are dropped here.

    This is the one place a key column may be assumed, because this job knows
    its screen. The generic exporter in gmes_core deliberately does not."""
    result = gmes_data.read_dataset(ws, RESULT_SCREEN, RESULT_DATASET, limit=-1)
    if not result.get("found"):
        return None, 0, 0

    real = [r for r in result["rows"] if r.get("poNo", "").strip()]
    dropped = len(result["rows"]) - len(real)

    path = os.path.join(target_dir, f"{REPORT_NAME}_{stamp}_data.csv")
    columns = [c for c in result["columns"] if not c.startswith("_")]
    import csv as _csv
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = _csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(real)
    return path, len(real), dropped


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="Plan date as YYYYMMDD (default: yesterday)")
    parser.add_argument("--days-back", type=int, default=1)
    parser.add_argument("--division", default="VD")
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    parser.add_argument("--no-csv", action="store_true",
                        help="skip the machine-readable CSV copy")
    parser.add_argument("--keep-open", action="store_true",
                        help="leave Chrome running after the job")
    args = parser.parse_args()

    plan_date = args.date or (datetime.now() - timedelta(days=args.days_back)).strftime("%Y%m%d")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 70)
    print(f"GMES daily export - {REPORT_NAME}")
    print(f"Plan date {plan_date}   Division {args.division}   started {stamp}")
    print("=" * 70)

    # Retried once: after a long idle the session expires, clicking AD SSO
    # produces no SSO window, and the second attempt signs in normally. An
    # unattended job should not fail on that.
    if not core.sign_in():
        print("\nFAILED: could not sign in to GMES.")
        return 1

    ws = connect_gmes()
    try:
        signed_in, who = is_logged_in(ws)
        print(f"\nSigned in as {who!r}." if signed_in else "\nWARNING: sign-in unconfirmed.")

        print(f"Screen: {ensure_screen(ws)}")

        print(f"Setting the plan date to {plan_date}...")
        print(f"  {set_plan_date(ws, plan_date)}")

        print(f"Selecting division {args.division}...")
        print(f"  {select_division(ws, args.division)}")

        print("Running the inquiry (waiting for the result set to settle)...")
        rows = run_inquiry(ws)
        print(f"  {rows} rows returned.")
        if rows == 0:
            print("\nFAILED: the query returned no rows. Nothing was exported.")
            cdp_common.screenshot_on_failure("gmes_daily_no_rows")
            return 1

        dates = verify_result_date(ws, plan_date)
        print(f"  plan dates in the result: {dates}")

        print("Downloading GMES's own Excel file...")
        downloaded = download_excel(ws, args.output_dir)
        final = deliver(downloaded, args.output_dir, stamp)
        drm = is_drm_protected(final)

        csv_path, real_rows, filler = (None, 0, 0)
        if not args.no_csv:
            print("Writing a machine-readable copy from the data layer...")
            csv_path, real_rows, filler = export_clean_data(
                ws, args.output_dir, stamp, plan_date)

        print("\n" + "=" * 70)
        print("DONE")
        print(f"  Excel : {final}")
        print(f"          {os.path.getsize(final) / 1024:,.1f} KB"
              + ("  [DRM-protected: opens in Excel, unreadable by other programs]"
                 if drm else ""))
        if csv_path:
            print(f"  CSV   : {csv_path}")
            print(f"          {real_rows} rows"
                  + (f" ({filler} blank filler rows dropped)" if filler else ""))
        print(f"  Date  : {plan_date}   Division: {args.division}")
        print("=" * 70)
        return 0

    except RuntimeError as e:
        print(f"\nFAILED: {e}")
        cdp_common.screenshot_on_failure("gmes_daily_failed")
        return 1
    finally:
        ws.close()
        if not args.keep_open and cdp_common.LAST_CHROME_PROCESS:
            print("Closing the automation browser.")
            try:
                cdp_common.LAST_CHROME_PROCESS.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
