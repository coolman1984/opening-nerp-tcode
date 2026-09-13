"""Sequential batch execution: one foreground screen and one global dialog."""
from ..browser.screenshots import screenshot_on_failure
from ..contracts import RunResult
from . import checkpoint, circuit, heartbeat
from .recovery import Ladder
from .run_screen_uc import run_screen


def run_many(session, specs, log=print, policy=None, resume=True):
    """Finish or fail each run before starting the next; never parallelize.

    Each screen gets the recovery ladder: a failure that is a fault rather
    than a refusal is repaired and retried, up to and including restarting
    the browser. A screen that has been attempted and still fails after that
    stops the batch - the foreground screen and the export dialog are
    global, so a run that ended in an unknown state makes every later screen
    unsafe.

    Two kinds of screen are skipped WITHOUT that risk, because neither one
    touches the browser at all, and the batch carries on past either of
    them to whatever comes after:

    * A screen the circuit breaker has already opened (Phase 50) - broken
      for days, not worth spending tonight's recovery budget on again.
    * A screen this exact batch already delivered before a full process
      crash (`resume=True`, the default) - already proved, by an earlier
      process, not worth doing twice.
    """
    specs = tuple(specs)
    ladder = Ladder(session, policy=policy, log=log)
    done = checkpoint.completed(specs) if resume else {}
    results = []
    for index, spec in enumerate(specs):
        heartbeat.beat(f"screen {spec.screen_code}")
        if spec.screen_code in done:
            entry = done[spec.screen_code]
            log(f"  RESUMED  : {spec.screen_code} already delivered "
                f"{entry.get('rows', 0)} rows before an earlier interruption")
            results.append(checkpoint.resumed_result(spec.screen_code, entry))
            continue
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
            if resume:
                checkpoint.record(specs, result)
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
    if resume and results and all(result.ok for result in results):
        checkpoint.clear(specs)
    return results
