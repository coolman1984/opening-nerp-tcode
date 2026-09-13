"""High-level G-MES operations that own browser/CDP session lifetime."""
from collections.abc import Callable, Iterable
from typing import Any

from ..contracts import DataExecution, LoginOutcome, RunExecution, RunSpec
from ..logging_setup import operation_log
from ..paths import automation_lock
from . import alerts
from .cli_inputs import build_run_specs
from .connect_uc import connect_gmes
from .data_uc import list_open_forms, read_dataset_pages, read_open_dataset
from .run_many_uc import run_many
from .session_uc import LiveSession
from .sign_in_uc import sign_in
from .workflow_uc import guide


def _logged(operation, log):
    return operation_log(operation) if log is print else _no_log()


class _no_log:
    def __enter__(self):
        return None

    def __exit__(self, *_args):
        return False


def execute_login(*, log=print, **kwargs):
    """Complete authentication and return its typed outcome."""
    with automation_lock(), _logged("login", log):
        return sign_in(log=log, **kwargs)


def _authenticated_connection(log, sign_in_kwargs):
    attempt = sign_in(log=log, **sign_in_kwargs)
    if attempt.outcome is not LoginOutcome.OK:
        return attempt, None
    return attempt, connect_gmes()


def _authenticated_session(log, sign_in_kwargs):
    """A connection that can also repair itself, for the operations that run
    long enough to need it. The sign-in arguments are carried along because
    a browser restart has to sign in again the same way this one did."""
    attempt, ws = _authenticated_connection(log, sign_in_kwargs)
    if ws is None:
        return attempt, None
    return attempt, LiveSession(ws, sign_in_kwargs, log=log)


def execute_run(specs: Iterable[RunSpec], *, log=print, resume=True,
                **sign_in_kwargs) -> RunExecution:
    """Authenticate, run sequentially, and close CDP before returning.

    `resume=True` (the default) picks up a batch a full process crash
    interrupted instead of redoing screens it already delivered
    (checkpoint.py). `resume=False` - `--fresh` on the CLI - always starts
    every screen from nothing, for the rare case that is genuinely wanted."""
    with automation_lock(), _logged("run", log):
        attempt, session = _authenticated_session(log, sign_in_kwargs)
        if session is None:
            execution = RunExecution(attempt)
        else:
            try:
                execution = RunExecution(attempt, tuple(run_many(session, specs, log=log, resume=resume)))
            finally:
                session.close()
        # A run that raised out of run_many (a genuine crash, not caught by
        # anything above) never reaches this line - which is correct: the
        # process is dying, and the external supervisor (Phase 52) is what
        # notices that, not an email this same process is trying to send.
        alerts.report_batch(execution, log=log)
        return execution


def execute_run_request(screens, *, log=print, resume=True, **kwargs) -> RunExecution:
    """Validate a CLI-shaped request, then run it through one operation."""
    return execute_run(build_run_specs(screens, **kwargs), log=log, resume=resume)


def execute_guided_workflow(interview, *, log=print, **sign_in_kwargs) -> DataExecution:
    """Sign in once, then let the operator choose from live screens.

    One authenticated session covers the whole interactive sitting: reading a
    screen's choices and running it are the same visit, so the screen the
    operator was shown is the screen that runs.
    """
    with automation_lock(), _logged("workflow", log):
        attempt, session = _authenticated_session(log, sign_in_kwargs)
        if session is None:
            return DataExecution(attempt)
        try:
            return DataExecution(attempt, value=guide(session, interview, log=log))
        finally:
            session.close()


def execute_data_forms(*, log=print, **sign_in_kwargs) -> DataExecution:
    """List current forms while the application owns the CDP session."""
    with automation_lock(), _logged("data", log):
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
    with automation_lock(), _logged("data", log):
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
    with automation_lock(), _logged("data", log):
        attempt, ws = _authenticated_connection(log, sign_in_kwargs)
        if ws is None:
            return DataExecution(attempt)
        try:
            value = consume(read_dataset_pages(ws, screen_code, dataset, page_size=page_size))
            return DataExecution(attempt, value=value)
        finally:
            ws.close()
