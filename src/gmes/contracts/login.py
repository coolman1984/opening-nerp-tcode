"""Login result shapes.

Replaces gmes_login.py's bare module constants (OK=0, FAILED=1,
REJECTED=2) with a named enum. The distinction they encode matters:
FAILED is transient and worth retrying once (an expired session
producing no SSO window); REJECTED is terminal and must NEVER be
retried, because retrying a bad-credential rejection against a
corporate directory risks locking the account (see HISTORY.md Phase 16).
An int is easy to compare against the wrong constant by accident; this
makes the two outcomes impossible to confuse.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class LoginOutcome(Enum):
    OK = auto()
    FAILED = auto()       # transient - safe to retry once
    REJECTED = auto()      # terminal - must not be retried


@dataclass(frozen=True, slots=True)
class CredentialUpdate:
    """Outcome of an explicit, local DPAPI credential update."""
    saved: bool
    message: str


@dataclass(frozen=True, slots=True)
class LoginAttempt:
    outcome: LoginOutcome
    detail: str = ""
    attempts_used: int = 1
