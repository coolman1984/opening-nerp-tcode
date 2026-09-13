"""Sequential batch execution: one foreground screen and one global dialog."""
from ..browser.screenshots import screenshot_on_failure
from ..contracts import RunResult
from .recovery import Ladder
from .run_screen_uc import run_screen


def run_many(session, specs, log=print, policy=None):
    """Finish or fail each run before starting the next; never parallelize.

    Each screen gets the recovery ladder: a failure that is a fault rather
    than a refusal is repaired and retried, up to and including restarting
    the browser. A screen that still fails after that stops the batch, which
    is unchanged - the foreground screen and the export dialog are global, so
    a run that ended in an unknown state makes every later run unsafe.
    """
    specs = tuple(specs)
    ladder = Ladder(session, policy=policy, log=log)
    results = []
    for index, spec in enumerate(specs):
        try:
            results.append(ladder.run(lambda ws: run_screen(ws, spec, log=log),
                                      what=spec.screen_code))
        except Exception as error:
            log(f"  FAILED   : {error}")
            try:
                screenshot_on_failure(f"gmes_{spec.screen_code}")
            except Exception as diagnostic_error:
                log(f"  diagnostic unavailable: {diagnostic_error}")
            results.append(RunResult(screen=spec.screen_code, ok=False, error=str(error)))
            for skipped in specs[index + 1:]:
                results.append(RunResult(screen=skipped.screen_code, ok=False,
                                         error="not run because the previous screen left an unknown state"))
            break
    return results
