"""Read-only diagnostic results for the public doctor command."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DoctorStatus(Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    status: DoctorStatus
    name: str
    detail: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def ok(self) -> bool:
        return not any(check.status is DoctorStatus.FAIL for check in self.checks)

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def render(self) -> str:
        return "\n".join(f"{check.status.value:<4} {check.name}: {check.detail}"
                         for check in self.checks)
