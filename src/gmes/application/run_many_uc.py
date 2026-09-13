"""Sequential batch execution: one foreground screen and one global dialog."""
from ..browser.screenshots import screenshot_on_failure
from ..contracts import RunResult
from . import circuit
from .recovery import Ladder
from .run_screen_uc import run_screen


def run_many(session, specs, log=print, policy=None):
    """Finish or fail each run before starting the next; never parallelize.

    Each screen gets the recovery ladder: a failure that is a fault rather
    than a refusal is repaired and retried, up to and including restarting
    the browser. A screen that has been attempted and still fails after that
    stops the batch - the foreground screen and the export dialog are
    global, so a run that ended in an unknown state makes every later run
    unsafe.

    A screen the circuit breaker has already opened is different: it is
    never opened at all, so nothing is left unclear behind it, and the
    batch carries on to whatever comes after it rather than losing an
    entire night's other reports to one screen that has been broken for
    days (HISTORY.md Phase 50).
    """
    specs = tuple(specs)
    ladder = Ladder(session, policy=policy, log=log)
    results = []
    for index, spec in enumerate(specs):
        if not spec.force:
            blocked = circuit.check(spec.screen_code)
            if blocked:
                log(f"  SKIPPED  : {blocked}")
                results.append(RunResult(screen=spec.screen_code, ok=False, error=blocked))
                continue
        try:
            result = ladder.run(lambda ws: run_screen(ws, spec, log=log),
                                what=spec.screen_code)
            circuit.record_success(spec.screen_code)
            results.append(result)
        except Exception as error:
            circuit.record_failure(spec.screen_code, str(error))
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
