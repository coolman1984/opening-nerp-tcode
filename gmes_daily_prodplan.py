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
from cdp_common import evaluate, send
import gmes_common
import gmes_data
import gmes_login
from gmes_common import click_control, connect_gmes, find_child_popups, is_logged_in

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "Data Hub Folder", "GMES")
REPORT_NAME = "Production Plan by Order(Line)"

# Screen codes from the breadcrumb - stable, unlike the window ids.
CONTAINER_SCREEN = "P1112UM00"   # what the search bar opens
FILTER_SCREEN = "P1112WF00"      # left panel: dates, and the Inquiry it feeds
RESULT_SCREEN = "P1112WM00"      # the grid's data
ORG_SCREEN = "OrgCategory_GDS"   # the Org tab's tree

RESULT_DATASET = "dsMasterProdPlan"
ORG_TREE_DATASET = "dsCatCommonTreeNodeDVO"

EXCEL_BTN = "mainframe.vFrameSet1.vFrameSet2.mdiFrame.form.btnExcel"


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def ensure_screen(ws, screen_code=CONTAINER_SCREEN, max_wait=90):
    """Make sure the report's screen is open, opening it if it is not.

    Without this the job silently depended on that screen happening to be
    the session's default. It is reached by screen code through the top
    search box - the same one entry point that reaches all 809 screens -
    rather than by walking four levels of menu."""
    import gmes_open_screen

    # Being open is not enough - it must be the tab in FRONT. A background
    # screen still accepts dataset writes, so the filters applied correctly
    # and the Inquiry click then landed on whichever screen was actually
    # visible, returning zero rows from the wrong report.
    for row in gmes_open_screen.open_screens(ws).get("rows", []):
        if screen_code.upper() in row.get("pageUrl", "").upper():
            win_id = row.get("winId", "")
            if gmes_open_screen.activate_screen(ws, win_id):
                return f"already open, activated tab {win_id}"
            return f"already open ({win_id}) but its tab could not be activated"

    print(f"  {screen_code} is not open; opening it via the search bar...")
    opened = gmes_open_screen.open_screen(ws, screen_code, timeout=max_wait)
    gmes_open_screen.activate_screen(ws, opened.get("winId", ""))

    # The tab existing is not the same as the screen being built.
    deadline = time.time() + max_wait
    while time.time() < deadline:
        forms = gmes_data.list_forms(ws)["forms"]
        if any((f["file"] or "").startswith(RESULT_SCREEN) for f in forms):
            return f"opened ({opened.get('title', screen_code)})"
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

    The row is found by its visible name, not by row number: the tree is
    built from the user's permissions and its order is not guaranteed."""
    js = """
    (function() {
        %s
        const hit = _dataset(%s, %s);
        if (!hit) return JSON.stringify({found: false});
        const ds = hit.ds;
        // Case-insensitive: a user typing "vd" must find "VD". An exact
        // comparison failed a real run with the answer sitting in the very
        // error message it printed.
        const wanted = String(%s).trim().toLowerCase();
        for (let r = 0; r < ds.getRowCount(); r++) {
            if (String(ds.getColumn(r, 'commonName')).trim().toLowerCase() !== wanted) continue;
            ds.setColumn(r, '_checked', 1);
            return JSON.stringify({found: true, row: r,
                                   pathKey: ds.getColumn(r, 'commonPathKey'),
                                   checked: String(ds.getColumn(r, '_checked'))});
        }
        const names = [];
        for (let r = 0; r < Math.min(ds.getRowCount(), 12); r++)
            names.push(String(ds.getColumn(r, 'commonName')));
        return JSON.stringify({found: false, available: names});
    })()
    """ % (gmes_data.JS_HELPERS, cdp_common.json.dumps(ORG_SCREEN),
           cdp_common.json.dumps(ORG_TREE_DATASET), cdp_common.json.dumps(name))

    result = evaluate(ws, js)
    if not result.get("found"):
        raise RuntimeError(
            f"Division {name!r} was not in the Org tree. "
            f"Divisions present: {result.get('available', '(tree not loaded)')}")
    return result


def run_inquiry(ws, max_wait=300, settle_checks=4, poll_interval=1.0,
                empty_grace=120):
    """Click Inquiry and wait until the result set has actually settled.

    The row count comes from the Dataset, not the grid: the grid only builds
    the rows on screen, so it can never say how many there really are.

    An empty dataset does NOT mean the query finished. Nexacro clears the
    result set the moment Inquiry is pressed and only refills it when the
    server answers, so the count sits at 0 for the whole round trip. Treating
    a few stable zero readings as "settled" made this report 0 rows and
    refuse to export while 790 rows were on their way - and a minute later
    they were on screen.

    So: settle only on a count above zero that has stopped moving, and give
    an all-zero run a long grace period before concluding there is genuinely
    no data. Neither figure is a guess at how long the query takes; both are
    generous caps on a loop that exits the moment it has its answer."""
    def row_count():
        result = gmes_data.read_dataset(ws, RESULT_SCREEN, RESULT_DATASET, limit=0)
        return result.get("total", -1) if result.get("found") else -1

    button = click_control(ws, cls="btn_LF_Search_New", text="Inquiry")
    if not button:
        raise RuntimeError("The Inquiry button was not found on the screen.")

    started = time.time()
    deadline = started + max_wait
    last, stable = None, 0

    while time.time() < deadline:
        time.sleep(poll_interval)
        count = row_count()

        # An alert instead of results - usually "no data found".
        popups = find_child_popups(ws)
        if popups.get("count"):
            names = [p["name"] for p in popups["popups"]]
            raise RuntimeError(f"GMES opened a dialog instead of returning results: {names}")

        if count > 0:
            stable = stable + 1 if count == last else 0
            last = count
            if stable >= settle_checks:
                return count
        else:
            last, stable = count, 0
            if time.time() - started > empty_grace:
                return 0

    raise RuntimeError(f"The query had not settled after {max_wait}s (last count: {last}).")


def verify_result_date(ws, expected_yyyymmdd):
    """Confirm the rows really are for the date we asked for.

    A stale result set from a previous query looks exactly like a fresh one,
    and an export of the wrong day is worse than no export at all."""
    result = gmes_data.read_dataset(ws, RESULT_SCREEN, RESULT_DATASET, limit=5)
    if not result.get("found") or not result["rows"]:
        return None
    dates = {row.get("planYmd", "").replace("-", "")[:8] for row in result["rows"]}
    dates.discard("")
    if dates and expected_yyyymmdd not in dates:
        raise RuntimeError(
            f"The results are for {sorted(dates)}, not the requested "
            f"{expected_yyyymmdd}. Refusing to export the wrong day.")
    return sorted(dates)


def download_excel(ws, target_dir, timeout=240):
    """Click the toolbar Excel icon, confirm the dialog, wait for the file.

    Chrome's download folder is redirected onto the SAME connection that
    does the clicking - setting it from a connection that is then closed
    leaves the file in the user's Downloads folder instead, which is exactly
    what happened the first time this was tried.

    The default Downloads folder is watched too, as a fallback."""
    os.makedirs(target_dir, exist_ok=True)
    downloads = os.path.join(os.environ.get("USERPROFILE", ""), "Downloads")

    try:
        send(ws, "Browser.setDownloadBehavior",
             {"behavior": "allow", "downloadPath": target_dir, "eventsEnabled": True})
    except Exception:
        send(ws, "Page.setDownloadBehavior",
             {"behavior": "allow", "downloadPath": target_dir})

    def snapshot(folder):
        try:
            return {f for f in os.listdir(folder) if f.lower().endswith((".xlsx", ".crdownload"))}
        except OSError:
            return set()

    before = {target_dir: snapshot(target_dir), downloads: snapshot(downloads)}

    icon = evaluate(ws, gmes_common.js_find_by_id(EXCEL_BTN))
    if not icon.get("found"):
        raise RuntimeError(f"The Excel Download icon was not visible ({icon.get('reason')}).")
    cdp_common.click_element_by_rect(ws, icon["x"], icon["y"])

    # The icon opens a "Save to Excel" dialog (PopupExcelExport) with the
    # grid already ticked; it does not download on its own.
    ok = click_control(ws, text="OK", attempts=30, delay=0.5)
    if not ok:
        raise RuntimeError("The 'Save to Excel' dialog did not offer an OK button.")

    deadline = time.time() + timeout
    while time.time() < deadline:
        for folder in (target_dir, downloads):
            new = snapshot(folder) - before[folder]
            finished = [f for f in new if f.lower().endswith(".xlsx")]
            if finished and not any(f.endswith(".crdownload") for f in new):
                path = os.path.join(folder, sorted(finished)[-1])
                # Wait for the size to stop growing before touching it.
                size = -1
                while size != os.path.getsize(path):
                    size = os.path.getsize(path)
                    time.sleep(0.5)
                return path
        time.sleep(1.0)

    raise RuntimeError(f"No .xlsx file appeared within {timeout}s.")


def deliver(downloaded_path, target_dir, stamp):
    """Move the export to its final name."""
    os.makedirs(target_dir, exist_ok=True)
    final = os.path.join(target_dir, f"{REPORT_NAME}_{stamp}.xlsx")
    if os.path.abspath(downloaded_path) != os.path.abspath(final):
        shutil.move(downloaded_path, final)
    return final


def is_drm_protected(path):
    """GMES exports come back wrapped by Samsung's NASCA DRM.

    The file opens normally in Excel on a machine running the DRM client,
    but it is NOT a readable workbook: the bytes are encrypted, so openpyxl,
    pandas and every other library see a corrupt file. Worth knowing before
    anything downstream tries to parse it."""
    try:
        with open(path, "rb") as fh:
            return b"NASCA DRM" in fh.read(64)
    except OSError:
        return False


def export_clean_data(ws, target_dir, stamp, plan_date):
    """Write a machine-readable copy straight from the Dataset.

    Two reasons this exists alongside the official download:
      * The GMES file is DRM-encrypted, so nothing downstream can read it.
      * The Dataset carries 85 filler rows with no PO and no master line
        that the grid hides. Exporting it raw would inflate the row count,
        so they are dropped here to match what the screen actually shows."""
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

    if gmes_login.main() != 0:
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
