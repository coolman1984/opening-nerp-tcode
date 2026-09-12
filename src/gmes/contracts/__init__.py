"""Typed shapes shared across the gmes package, replacing the loose
dicts gmes_core.py/gmes_profile.py/gmes_login.py/gmes_data.py pass
around today. Zero dependency on the modules being migrated away
from - these are pure data."""
from gmes.contracts.dataset import DatasetPage, DatasetResult
from gmes.contracts.doctor import DoctorCheck, DoctorReport, DoctorStatus
from gmes.contracts.execution import DataExecution, RunExecution
from gmes.contracts.login import CredentialUpdate, LoginAttempt, LoginOutcome
from gmes.contracts.profile import ProfileDrift, ProfileRecord
from gmes.contracts.run import ExportResult, RunResult, RunSpec
from gmes.contracts.screen import (
    FilterRef,
    GridRef,
    OptionRef,
    QuickViewRef,
    ScreenInfo,
    TreeRef,
)

__all__ = [
    "DatasetPage",
    "DatasetResult",
    "DoctorCheck",
    "DoctorReport",
    "DoctorStatus",
    "DataExecution",
    "CredentialUpdate",
    "LoginAttempt",
    "LoginOutcome",
    "ProfileDrift",
    "ProfileRecord",
    "ExportResult",
    "RunResult",
    "RunExecution",
    "RunSpec",
    "FilterRef",
    "GridRef",
    "OptionRef",
    "QuickViewRef",
    "ScreenInfo",
    "TreeRef",
]
