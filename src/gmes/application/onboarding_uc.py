"""Get a usable login on a machine that has never had one.

The program is meant to reach other people in the factory. On their machine
there is no credential store, or there is one that came along inside a
copied folder and belongs to somebody else - Windows DPAPI makes that second
one undecryptable, so it reads back as nothing at all.

Until now both of those ended the run with "no saved credentials", which is
true and useless: it does not say that the person can fix it in ten seconds,
and it does not offer them the box to do it in. A window for exactly that
already existed (`auth/credentials.ask_in_window`) and was only ever reached
by running `gmes credentials set` on purpose.

The one thing this must not do is hang. The nightly job runs with nobody in
the office, and a modal window waiting for a password nobody will type is a
worse failure than the error message it replaced - the job would still be
sitting there in the morning. So the prompt is offered only when somebody
could actually answer it, and even then it closes itself.
"""
import sys

from ..auth import credentials, install


def someone_is_here():
    """Whether a person could answer a question right now.

    A console attached to the process is the signal: the guided workflow and
    the `.bat` launcher have one, and Task Scheduler does not."""
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except (AttributeError, OSError, ValueError):
        return False


def obtain_credentials(log=print, prompt=None, interactive=None, timeout_s=300):
    """Return (user, password), asking for them when this machine has none.

    Returns (None, None) rather than raising when nobody is here to answer,
    so the caller reports its own honest "not signed in" outcome instead of
    this module deciding what an unattended run should do.
    """
    user, password = credentials.load()
    if user and password:
        return user, password

    state = install.inspect()
    log(f"No usable G-MES login is stored on this computer - {state.describe()}.")
    if not (someone_is_here() if interactive is None else interactive):
        log("Nobody is at the keyboard, so there is nothing to ask. Run "
            "'gmes credentials set' once on this computer, then this job can "
            "run unattended.")
        return None, None

    log("Opening a box to save one. It is encrypted with this Windows "
        "account's own key and can only be read back on this computer.")
    asked = prompt or credentials.ask_in_window
    user, password = asked(timeout_s=timeout_s)
    if not (user and password):
        log("Nothing was entered, so nothing was saved.")
        return None, None

    credentials.save(user, password)
    log("Saved. This computer will not ask again.")
    return user, password


def claim_installation(log=print):
    """Record that a sign-in has actually worked here.

    Called after success, never on the way in: recording first would turn an
    interrupted first run into a machine that claims to be set up and is not.
    A failure to write the record is not a failure of the run - the sign-in
    already worked, and the only cost is being asked the same question
    again next time."""
    state = install.inspect()
    if not state.is_new_here:
        return False
    try:
        install.record()
    except OSError as error:
        log(f"(could not record this installation: {error})")
        return False
    log("This computer is now set up for G-MES automation.")
    return True
