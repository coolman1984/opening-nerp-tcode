"""High-level G-MES operations that own browser/CDP session lifetime."""
from collections.abc import Callable, Iterable
from typing import Any

from ..contracts import DataExecution, LoginOutcome, RunExecution, RunSpec
from ..logging_setup import operation_log
from .cli_inputs import build_run_specs
from .connect_uc import connect_gmes
from .data_uc import list_open_forms, read_dataset_pages, read_open_dataset
from .run_many_uc import run_many
from .sign_in_uc import sign_in


def _logged(operation, log):
    return operation_log(operation) if log is print else _no_log()


class _no_log:
    def __enter__(self):
        return None

    def __exit__(self, *_args):
        return False


def execute_login(*, log=print, **kwargs):
    """Complete authentication and return its typed outcome."""
    with _logged("login", log):
        return sign_in(log=log, **kwargs)


def _authenticated_connection(log, sign_in_kwargs):
    attempt = sign_in(log=log, **sign_in_kwargs)
    if attempt.outcome is not LoginOutcome.OK:
        return attempt, None
    return attempt, connect_gmes()


def execute_run(specs: Iterable[RunSpec], *, log=print, **sign_in_kwargs) -> RunExecution:
    """Authenticate, run sequentially, and close CDP before returning."""
    with _logged("run", log):
        attempt, ws = _authenticated_connection(log, sign_in_kwargs)
        if ws is None:
            return RunExecution(attempt)
        try:
            return RunExecution(attempt, tuple(run_many(ws, specs, log=log)))
        finally:
            ws.close()


def execute_run_request(screens, *, log=print, **kwargs) -> RunExecution:
    """Validate a CLI-shaped request, then run it through one operation."""
    return execute_run(build_run_specs(screens, **kwargs), log=log)


def execute_data_forms(*, log=print, **sign_in_kwargs) -> DataExecution:
    """List current forms while the application owns the CDP session."""
    with _logged("data", log):
        attempt, ws = _authenticated_connection(log, sign_in_kwargs)
        if ws is None:
            return DataExecution(attempt)
        try:
            return DataExecution(attempt, value=list_open_forms(ws))
        finally:
            ws.close()


def execute_data_read(screen_code, dataset, *, limit=20, offset=0, log=print,
                      **sign_in_kwargs) -> DataExecution:
    """Read one bounded dataset while the application owns the CDP session."""
    with _logged("data", log):
        attempt, ws = _authenticated_connection(log, sign_in_kwargs)
        if ws is None:
            return DataExecution(attempt)
        try:
            return DataExecution(attempt, data=read_open_dataset(
                ws, screen_code, dataset, limit=limit, offset=offset))
        finally:
            ws.close()


def execute_data_stream(screen_code, dataset,
                        consume: Callable[[Iterable], Any], *, page_size=300,
                        log=print, **sign_in_kwargs) -> DataExecution:
    """Let a specialized consumer process data pages without seeing CDP."""
    with _logged("data", log):
        attempt, ws = _authenticated_connection(log, sign_in_kwargs)
        if ws is None:
            return DataExecution(attempt)
        try:
            value = consume(read_dataset_pages(ws, screen_code, dataset, page_size=page_size))
            return DataExecution(attempt, value=value)
        finally:
            ws.close()
