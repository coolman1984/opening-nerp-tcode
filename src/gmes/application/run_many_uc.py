"""Sequential batch execution: one foreground screen and one global dialog."""
from ..browser.screenshots import screenshot_on_failure
from ..contracts import RunResult
from .run_screen_uc import run_screen


def run_many(ws, specs, log=print):
    """Finish or fail each run before starting the next; never parallelize."""
    results = []
    for spec in specs:
        try:
            results.append(run_screen(ws, spec, log=log))
        except Exception as error:
            log(f"  FAILED   : {error}")
            try:
                screenshot_on_failure(f"gmes_{spec.screen_code}")
            except Exception as diagnostic_error:
                log(f"  diagnostic unavailable: {diagnostic_error}")
            results.append(RunResult(screen=spec.screen_code, ok=False, error=str(error)))
    return results
