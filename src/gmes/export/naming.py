"""Generic Windows-safe output naming for G-MES exports."""
import re


def safe_name(text):
    """Return a Windows-safe report filename stem."""
    return re.sub(r'[<>:"/\\|?*]', "-", (text or "").strip()) or "report"


__all__ = ["safe_name"]
