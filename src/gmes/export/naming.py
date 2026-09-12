"""Output names shared by G-MES exports.

Names remain deliberately boring: the Production Plan job has an existing
downstream convention, so this module preserves it rather than introducing a
new date or title format during the migration.
"""
import re


PRODUCTION_PLAN_NAME = "Production Plan by Order(Line)"


def safe_name(text):
    """Return a Windows-safe report filename stem."""
    return re.sub(r'[<>:"/\\|?*]', "-", (text or "").strip()) or "report"


def production_plan_filename(stamp, data=False):
    """Return the established Production Plan Excel or data-CSV filename."""
    suffix = "_data.csv" if data else ".xlsx"
    return f"{PRODUCTION_PLAN_NAME}_{stamp}{suffix}"
