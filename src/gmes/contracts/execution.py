"""Typed outcomes returned by application operations, never infrastructure."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .login import LoginAttempt, LoginOutcome
from .run import RunResult


@dataclass(frozen=True, slots=True)
class RunExecution:
    """The sign-in outcome and all completed screen runs."""
    login: LoginAttempt
    results: tuple[RunResult, ...] = ()

    @property
    def ok(self) -> bool:
        return self.login.outcome is LoginOutcome.OK


@dataclass(frozen=True, slots=True)
class DataExecution:
    """The sign-in outcome and a generic data-capability result."""
    login: LoginAttempt
    data: dict[str, Any] | None = None
    value: Any = None

    @property
    def ok(self) -> bool:
        return self.login.outcome is LoginOutcome.OK
