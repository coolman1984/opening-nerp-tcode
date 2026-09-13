"""Climb a ladder of increasingly drastic recoveries instead of giving up.

The nightly job runs with nobody in the office. One transient failure - a
dropped socket, a page that did not build, a notice over the Inquiry button -
used to end the whole night, and the report was simply missing in the
morning.

Retrying the same attempt is not the answer either: an attempt that failed
for a reason that is still true will fail again, and a loop of identical
attempts burns the night as effectively as stopping did. So each retry is
preceded by a DIFFERENT and more drastic repair, and the run only gets the
next rung once the cheaper one has been tried:

    rung 1  in place    reattach a dead socket, clear notice popups
    rung 2  reset page  prune the engine cache, clear the browser cache,
                        reload, and wait for the application to rebuild
    rung 3  cold start  close the automation browser, start it again,
                        sign in again, reattach
    rung 4  stop        screenshot and report the last real reason

Two limits keep this bounded. A wall-clock budget covers all attempts
together, and the cold start is allowed a fixed small number of times - a
ladder with no top is just a loop.

And one class of failure never gets retried at all. "No filter matches
`porder`", "which grid? this screen has:", "the division did not take" are
not faults; they are this project's refusals, working exactly as intended
(CLAUDE.md 3.5/3.9). Nothing about repeating them changes the answer, and
retrying one hides the real problem behind three identical attempts.
"""
import time
from dataclasses import dataclass


# Phrases this project's own code raises when it has DECIDED something is
# wrong, rather than when something broke. Matched on the message because
# that is what these deliberate refusals actually carry - they are all
# RuntimeError, so the type tells us nothing.
DECISIONS = (
    "no filter matches", "is ambiguous", "which grid", "more than one plausible",
    "did not take", "refusing", "remembered screen shape changed",
    "has no date field", "no field for", "has no from/to pair",
    "is not in any category tree", "no category tree", "cannot be set",
    "returned no rows", "requires --verify", "unknown export format",
    "not permitted", "no saved credentials", "already running",
)


def is_a_decision(error):
    """Whether this is the automation refusing, rather than something broken.

    A refusal is a finished answer. Repeating it produces the same answer
    more slowly, and buries the sentence that explains the run under two
    identical copies of itself."""
    if isinstance(error, (ValueError, TypeError)):
        return True
    message = str(error).casefold()
    return any(mark in message for mark in DECISIONS)


@dataclass(frozen=True)
class RecoveryPolicy:
    """How far to climb, and when to stop climbing.

    `in_place_attempts` counts attempts, not repairs: the first attempt is
    the plain one, so a value of 3 means the plain attempt plus rung 1 plus
    rung 2. `time_budget` covers everything together, because the point of
    the budget is that the job ends before the morning shift, whatever it is
    spending its time on."""
    in_place_attempts: int = 3
    cold_starts: int = 1
    time_budget_s: float = 1800.0


class Ladder:
    """Runs one piece of work, repairing between attempts.

    The session is anything exposing `ws`, `settle()`, `reset_page()` and
    `cold_start()`; `application/runtime_uc.py` owns the real one. Keeping
    it behind those four names is what lets this be tested without a
    browser - and what stops the ladder deciding anything about Chrome.
    """

    def __init__(self, session, policy=None, log=print):
        self.session = session
        self.policy = policy or RecoveryPolicy()
        self.log = log

    def run(self, work, what=""):
        """Call `work(ws)`, climbing the ladder until it succeeds or stops.

        Re-raises the last real failure. The caller keeps its own failure
        reporting - this only decides how many times, and after what
        repair, the attempt is worth making again."""
        deadline = time.monotonic() + self.policy.time_budget_s
        attempts, cold_starts = 0, 0
        while True:
            attempts += 1
            try:
                return work(self.session.ws)
            except Exception as error:
                if is_a_decision(error):
                    self.log(f"  recovery : not a fault - {error}")
                    raise
                left = deadline - time.monotonic()
                if left <= 0:
                    self.log(f"  recovery : out of time after {attempts} attempts")
                    raise
                rung = self._repair(attempts, cold_starts, error, what)
                if rung is None:
                    self.log(f"  recovery : nothing further to try after {attempts} attempts")
                    raise
                if rung == "cold start":
                    cold_starts += 1

    def _repair(self, attempts, cold_starts, error, what):
        """Perform the next repair up, and name it. None means the top."""
        target = f" of {what}" if what else ""
        if attempts < self.policy.in_place_attempts:
            rung = "in place" if attempts == 1 else "reset page"
            self.log(f"  recovery : attempt {attempts}{target} failed ({error}); "
                     f"repairing {rung} and trying again")
            if rung == "in place":
                self.session.settle()
            else:
                self.session.reset_page()
            return rung
        if cold_starts < self.policy.cold_starts:
            self.log(f"  recovery : attempt {attempts}{target} failed ({error}); "
                     "restarting the browser and signing in again")
            self.session.cold_start()
            return "cold start"
        return None
