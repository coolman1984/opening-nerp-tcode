"""Read-only readiness inspection for the standalone G-MES application."""
from __future__ import annotations

import importlib.util
import os
import platform
import sys
from datetime import datetime, timedelta
from pathlib import Path

from ..browser.cdp import cdp_is_up, get_tabs
from ..browser.chrome import find_chrome, working_profile_dir
from ..contracts import DoctorCheck, DoctorReport, DoctorStatus
from ..paths import gmes_root


def _status_for_path(path: Path, label: str) -> DoctorCheck:
    if path.exists():
        access = os.access(path, os.R_OK | os.W_OK)
        return DoctorCheck(DoctorStatus.PASS if access else DoctorStatus.FAIL, label,
                           "readable and writable" if access else "exists but is not writable")
    parent = path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    accessible = os.access(parent, os.W_OK)
    return DoctorCheck(DoctorStatus.WARN if accessible else DoctorStatus.FAIL, label,
                       f"not created yet; parent {parent} is " + ("writable" if accessible else "not writable"))


def _profile_health(directory: Path) -> DoctorCheck:
    if not directory.exists():
        return DoctorCheck(DoctorStatus.WARN, "profiles", "directory not created yet")
    invalid = 0
    for path in directory.glob("*.json"):
        try:
            import json
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            invalid += 1
    state = f"{len(list(directory.glob('*.json')))} profile(s)"
    if invalid:
        return DoctorCheck(DoctorStatus.WARN, "profiles", f"{state}; {invalid} unreadable or invalid")
    return DoctorCheck(DoctorStatus.PASS, "profiles", f"{state}; JSON readable")


def _automation_profile(directory: Path) -> DoctorCheck:
    if not directory.exists():
        return DoctorCheck(DoctorStatus.WARN, "automation profile", "not created yet")
    age = datetime.now() - datetime.fromtimestamp(directory.stat().st_mtime)
    if age > timedelta(days=30):
        return DoctorCheck(DoctorStatus.WARN, "automation profile",
                           f"exists; last changed {age.days} days ago")
    return DoctorCheck(DoctorStatus.PASS, "automation profile", "exists")


def inspect(*, root: Path | None = None, env=None, chrome_locator=find_chrome,
            cdp_probe=cdp_is_up, tab_probe=get_tabs, profile_dir=None) -> DoctorReport:
    """Observe prerequisites only. This function never creates or repairs state."""
    environment = os.environ if env is None else env
    runtime = Path(root) if root is not None else gmes_root()
    checks = [
        DoctorCheck(DoctorStatus.PASS, "Windows", platform.platform()),
        DoctorCheck(DoctorStatus.PASS, "package", "frozen executable" if getattr(sys, "frozen", False)
                    else f"source Python {sys.version.split()[0]}"),
        DoctorCheck(DoctorStatus.PASS if importlib.util.find_spec("websocket") else DoctorStatus.FAIL,
                    "websocket-client", "available" if importlib.util.find_spec("websocket") else "not installed"),
        _status_for_path(runtime, "runtime root"),
        _status_for_path(runtime / "logs", "logs"),
        _status_for_path(runtime / "screenshots", "screenshots"),
        _status_for_path(runtime / "config", "config"),
        _status_for_path(runtime / "evidence", "evidence"),
        _profile_health(runtime / "profiles"),
        _automation_profile(Path(profile_dir) if profile_dir is not None else Path(working_profile_dir())),
    ]
    try:
        checks.append(DoctorCheck(DoctorStatus.PASS, "Chrome", str(chrome_locator())))
    except RuntimeError as error:
        checks.append(DoctorCheck(DoctorStatus.FAIL, "Chrome", str(error)))

    bypass = environment.get("NO_PROXY", environment.get("no_proxy", ""))
    proxy_status = DoctorStatus.PASS if "localhost" in bypass and "127.0.0.1" in bypass else DoctorStatus.WARN
    checks.append(DoctorCheck(proxy_status, "CDP proxy bypass",
                              "localhost and 127.0.0.1 bypassed" if proxy_status is DoctorStatus.PASS
                              else "CDP may be intercepted; launch through GMES.exe"))
    try:
        up = cdp_probe()
        detail = f"available; {len(tab_probe())} target(s)" if up else "not running (start with gmes login)"
        checks.append(DoctorCheck(DoctorStatus.PASS if up else DoctorStatus.WARN, "CDP", detail))
    except Exception as error:
        checks.append(DoctorCheck(DoctorStatus.WARN, "CDP", f"unavailable: {error}"))
    checks.append(DoctorCheck(DoctorStatus.PASS if (runtime / "credentials.dat").is_file() else DoctorStatus.WARN,
                              "credential store", "DPAPI store present" if (runtime / "credentials.dat").is_file()
                              else "not present; use explicit gmes migrate or credential setup"))
    return DoctorReport(tuple(checks))
