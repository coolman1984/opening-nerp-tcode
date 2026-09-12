"""Public application interface for CLI and specialized consumers."""
from .._version import __version__
from ..contracts import LoginOutcome
from .cli_inputs import build_run_specs
from .connect_uc import connect_gmes
from .data_uc import list_open_forms, read_dataset_pages, read_open_dataset
from .migration_uc import migrate_credentials
from .run_many_uc import run_many
from .run_screen_uc import default_output_dir, print_summary, run_screen
from .sign_in_uc import date_from_args, sign_in


def package_version():
    """Return the installed standalone package version without side effects."""
    return __version__


def sign_in_ok(**kwargs):
    """Run typed sign-in and expose only success/failure to presentation."""
    return sign_in(**kwargs).outcome is LoginOutcome.OK


# Public names intentionally form the sole seam used by cli/ and examples/.
read_dataset = read_open_dataset
list_forms = list_open_forms

__all__ = ["build_run_specs", "connect_gmes", "date_from_args", "default_output_dir",
           "list_forms", "migrate_credentials", "package_version", "print_summary",
           "read_dataset", "read_dataset_pages", "run_many", "run_screen", "sign_in_ok"]
