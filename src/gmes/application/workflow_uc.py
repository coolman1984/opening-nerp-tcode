"""Read a live screen's choices, then run what the operator picked from them.

The guided workflow used to ask its questions against a blank prompt. It knew
the screen code and nothing else, so "Extra filters as Name=Value" and
"Options separated by commas" were asked of a person who had to remember how
a column was spelled in a system that shows them a label instead. A typo was
indistinguishable from a filter that does not exist, and the only way to find
out was to run.

The screen has always known its own answer. This opens it first, reads what
it offers, and hands that to the caller to present - so a choice is made from
a list of what is actually there, which is also the only way to choose an
option that REBUILDS the panel without discovering it by accident.

Presentation and questions belong to the caller. This module owns the order:
open, read, ask, run, report.
"""
from ..contracts import ScreenPreview
from ..discovery.screen import open_screen
from .run_many_uc import run_many
from .cli_inputs import build_run_specs
from .run_screen_uc import clear_notices


def build_preview(screen):
    """Everything this screen offers, read from the screen itself.

    `date_columns` is only populated when the grid already holds rows - on a
    screen that has not been queried yet there is nothing to sample, and an
    empty tuple says exactly that. An ambiguous result grid is reported as a
    warning rather than raised: the whole point of a preview is to show the
    operator the problem before the run hits it."""
    warnings = list(screen.warnings)
    date_columns = ()
    try:
        grid = screen.grid()
        date_columns = tuple(screen.date_like_columns(grid))
    except RuntimeError as error:
        warnings.append(str(error))
    return ScreenPreview(
        code=screen.code, title=screen.title,
        filters=tuple(screen.filters), unbound=tuple(screen.unbound),
        options=tuple(screen.options()), trees=tuple(screen.trees()),
        quick_views=tuple(screen.info.quick_views), grids=tuple(screen.info.grids),
        date_columns=date_columns, warnings=tuple(warnings))


def preview_screen(ws, code, log=print):
    """Open one screen, clear what is covering it, and read its choices."""
    screen = open_screen(ws, code, log=log)
    clear_notices(ws, log, "screen open")
    return build_preview(screen)


def guide(session, interview, log=print):
    """Run the ask-from-what-is-there loop until the operator stops.

    Returns True when every screen the operator ran finished; the caller
    turns that into an exit code. A screen that fails does not end the
    session - the operator may want to try another one - but it is
    remembered, so the command does not exit 0 on a run that stopped.

    The session is read for its socket on each pass rather than once at the
    top: a run that had to restart the browser to recover replaced it, and a
    handle taken before that points at a connection that is gone."""
    completed = True
    while True:
        code, profile = interview.choose_screen()
        if not code:
            return False
        try:
            preview = preview_screen(session.ws, code, log=log)
        except RuntimeError as error:
            # Opening is the one step with nothing to show afterwards: there
            # is no screen to read, so there are no choices to offer.
            log(f"STOPPED: {error}")
            interview.report_open_failure(code, str(error))
            completed = False
            if not interview.again():
                return completed
            continue

        request = interview.choose_values(preview, profile)
        if request is None:
            if not interview.again():
                return completed
            continue

        specs = build_run_specs([code], **request)
        result = run_many(session, specs, log=log)[0]
        interview.report(result)
        completed = completed and result.ok
        if not interview.again():
            return completed
