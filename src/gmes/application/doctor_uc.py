"""Application boundary for the read-only diagnostics capability."""
from ..diagnostics.doctor import inspect


def execute_doctor():
    return inspect()
