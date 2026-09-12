"""Specialized nightly Production Plan policy outside generic G-MES."""
import csv
import itertools
import os
from dataclasses import replace
from datetime import datetime

from gmes.application import facade as gmes
from gmes.contracts import RunSpec

CONTAINER_SCREEN = "P1112UM00"
RESULT_DATASET = "dsMasterProdPlan"


def production_plan_filename(stamp, data=False):
    suffix = "_data.csv" if data else ".xlsx"
    return f"Production Plan by Order(Line)_{stamp}{suffix}"


def export_clean_data(ws, target_dir, stamp):
    """Drop this report's LINE SUM/PROC SUM records using its known poNo rule."""
    pages = iter(gmes.read_dataset_pages(ws, CONTAINER_SCREEN, RESULT_DATASET))
    first = next(pages, None)
    if first is None or not first.rows:
        return None, 0, 0
    columns = [column for column in first.rows[0] if not column.startswith("_")]
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, production_plan_filename(stamp, data=True))
    written, dropped = 0, 0
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for page in itertools.chain((first,), pages):
            for row in page.rows:
                if str(row.get("poNo") or "").strip():
                    writer.writerow(row)
                    written += 1
                else:
                    dropped += 1
    return path, written, dropped


def run_production_plan(ws, date=None, days_back=1, division="VD", out_dir=None,
                        no_csv=False, log=print):
    """Run an opt-in specialized policy through the generic run interface."""
    plan_date = gmes.date_from_args(date) if date else gmes.date_from_args(days_back=days_back)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    directory = out_dir or gmes.default_output_dir()
    result = gmes.run_screen(ws, RunSpec(
        CONTAINER_SCREEN, division=division, date_from=plan_date, date_to=plan_date,
        grid_name=RESULT_DATASET, verify=("planYmd", plan_date), export="xlsx",
        out_dir=directory, use_profile=False), log=log)
    if not result.ok:
        return result
    files = []
    for path in result.files:
        final = os.path.join(directory, production_plan_filename(stamp))
        if os.path.abspath(path) != os.path.abspath(final):
            os.replace(path, final)
        files.append(final)
    written = 0
    if not no_csv:
        path, written, dropped = export_clean_data(ws, directory, stamp)
        if path:
            files.append(path)
            log(f"  CSV: {written} rows ({dropped} subtotal rows dropped)")
    return replace(result, files=tuple(files), csv_rows=written)
