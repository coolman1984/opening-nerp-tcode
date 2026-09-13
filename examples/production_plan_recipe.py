"""Specialized nightly Production Plan policy outside generic G-MES."""
import csv
import itertools
import os
import re
from dataclasses import replace
from datetime import datetime, timedelta

from gmes.application import facade as gmes
from gmes.contracts import LoginOutcome, RunResult, RunSpec

CONTAINER_SCREEN = "P1112UM00"
RESULT_DATASET = "dsMasterProdPlan"


def production_plan_filename(stamp, data=False):
    suffix = "_data.csv" if data else ".xlsx"
    return f"Production Plan by Order(Line)_{stamp}{suffix}"


def _plan_date(value, days_back):
    if value:
        digits = re.sub(r"[^\d]", "", value)
        if len(digits) != 8:
            raise ValueError("date must be YYYYMMDD or YYYY-MM-DD")
        return datetime.strptime(digits, "%Y%m%d").strftime("%Y%m%d")
    return (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")


def export_clean_data(source_path, target_dir, stamp):
    """Create the report-specific clean CSV from this exact run's generic CSV."""
    with open(source_path, "r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames:
            raise RuntimeError("the generic CSV has no header")
        os.makedirs(target_dir, exist_ok=True)
        path = os.path.join(target_dir, production_plan_filename(stamp, data=True))
        temporary = path + ".partial"
        written, dropped = 0, 0
        try:
            with open(temporary, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=reader.fieldnames, extrasaction="ignore")
                writer.writeheader()
                for row in reader:
                    if str(row.get("poNo") or "").strip():
                        writer.writerow(row)
                        written += 1
                    else:
                        dropped += 1
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
    if written == 0:
        raise RuntimeError("the report CSV contains no production-order rows")
    return path, written, dropped


def run_production_plan(date=None, days_back=1, division="VD", out_dir=None,
                        no_csv=False, log=print):
    """Run an opt-in specialized policy through the generic run interface."""
    plan_date = _plan_date(date, days_back)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    directory = out_dir or os.path.join(os.getcwd(), "Data Hub Folder", "GMES")
    execution = gmes.execute_run((RunSpec(
        CONTAINER_SCREEN, division=division, date_from=plan_date, date_to=plan_date,
        grid_name=RESULT_DATASET, verify=("planYmd", plan_date), export="both",
        out_dir=directory, use_profile=False),), log=log)
    if execution.login.outcome is not LoginOutcome.OK:
        return RunResult(CONTAINER_SCREEN, False,
                         error=execution.login.detail or "sign-in did not complete")
    if not execution.results:
        return RunResult(CONTAINER_SCREEN, False, error="run operation returned no result")
    result = execution.results[0]
    if not result.ok:
        return result
    files = []
    for path in result.files:
        if path.lower().endswith(".xlsx"):
            final = os.path.join(directory, production_plan_filename(stamp))
            if os.path.abspath(path) != os.path.abspath(final):
                os.replace(path, final)
            files.append(final)
        else:
            files.append(path)
    written = 0
    if not no_csv:
        generic = next((path for path in result.files if path.lower().endswith(".csv")), None)
        if not generic:
            return replace(result, ok=False, error="the same-run CSV was not produced")
        path, written, dropped = export_clean_data(generic, directory, stamp)
        try:
            os.unlink(generic)
        except OSError:
            pass
        files = [path if item == generic else item for item in files]
        log(f"  CSV: {written} rows ({dropped} subtotal rows dropped)")
    return replace(result, files=tuple(files), csv_rows=written)
