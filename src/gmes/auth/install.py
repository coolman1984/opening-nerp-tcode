"""Which machine and Windows account this installation belongs to.

The program is meant to reach other people in the factory, and a copied
folder is the ordinary way that happens. When the runtime tree arrives from
somewhere else it carries an `install.json` and a `credentials.dat` that
describe a different person, and the honest thing to do is notice and say
so - rather than report "no saved credentials" for a file that is sitting
right there, or, worse, behave as though the previous owner were signed in.

Windows DPAPI already makes the second of those impossible: a credential
store encrypted for one Windows account simply cannot be decrypted by
another, on any machine. That is the real protection. What this module adds
is the ability to TELL THE DIFFERENCE between "nobody has set this up yet"
and "this was set up by somebody else", because those need different
sentences to be said to the person sitting in front of it.

Nothing here deletes anything. A stale record is replaced by a new one only
once a new identity has actually been established; a mismatch on its own
never removes a credential store, a screen profile, or a browser profile
(CLAUDE.md 2.1a).

The fingerprint is a digest rather than the names themselves. Comparison is
all that is ever needed, and a file nobody can read anything out of is one
less thing to think about when this tree is copied around.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime

from ..paths import install_path


def fingerprint():
    """A stable digest of this Windows account on this machine.

    Both halves matter. The same person on a different PC needs their own
    browser profile and their own session; a different person on the same PC
    has a different DPAPI key and cannot read the first one's store."""
    identity = "|".join(os.environ.get(name, "") for name in
                        ("COMPUTERNAME", "USERDOMAIN", "USERNAME"))
    return hashlib.sha256(identity.encode("utf-8", "replace")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class Installation:
    """What is known about where this installation has been.

    `first_run` means nothing has ever been recorded here. `moved` means
    something was, for a different machine or account - the interesting
    case, and the one a plain "is there a credential file" test cannot see.
    """
    fingerprint: str
    first_run: bool = False
    moved: bool = False
    recorded: str = ""

    @property
    def is_new_here(self) -> bool:
        return self.first_run or self.moved

    def describe(self):
        if self.first_run:
            return "this is the first run on this computer"
        if self.moved:
            return (f"this installation was set up on another computer or "
                    f"Windows account (recorded {self.recorded or 'at an unknown time'}); "
                    "nothing saved by that one can be used here")
        return "this installation belongs to this computer and account"


def inspect() -> Installation:
    """Read the record without writing one. Safe to call at any time."""
    here = fingerprint()
    path = install_path()
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        # No record, or one that cannot be read. Either way nothing here can
        # be trusted to describe this machine, and a corrupt file is not a
        # reason to refuse to run.
        return Installation(here, first_run=True)
    if not isinstance(data, dict) or data.get("fingerprint") != here:
        return Installation(here, moved=True,
                            recorded=str((data or {}).get("recorded", ""))
                            if isinstance(data, dict) else "")
    return Installation(here, recorded=str(data.get("recorded", "")))


def record() -> str:
    """Claim this installation for this machine and account.

    Called once a sign-in has actually been established here, not on the way
    in: recording first would turn an interrupted first run into a machine
    that claims to be set up and is not."""
    path = install_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fingerprint": fingerprint(),
               "recorded": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    fd, temporary = tempfile.mkstemp(prefix=".install-", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return str(path)
