"""Public G-MES capabilities: typed outcomes, never infrastructure handles."""
from .._version import __version__
from .credentials_uc import set_credentials
from .doctor_uc import execute_doctor
from .migration_uc import migrate_credentials
from .runtime_uc import (execute_data_forms, execute_data_read, execute_data_stream,
                         execute_login, execute_run, execute_run_request)


def package_version():
    """Return the installed standalone package version without side effects."""
    return __version__


__all__ = ["execute_data_forms", "execute_data_read", "execute_data_stream", "execute_doctor",
           "execute_login", "execute_run", "execute_run_request", "migrate_credentials",
           "package_version", "set_credentials"]
