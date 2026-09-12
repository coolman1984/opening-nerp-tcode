"""Stdout-teeing, redacted operation logging under `%LOCALAPPDATA%\\GMES`."""
from __future__ import annotations

import re
import sys
from contextlib import contextmanager, redirect_stdout
from datetime import datetime

from .paths import log_path


_SECRET = re.compile(r"(?i)\b(password|token(?:id)?|refreshtokenid)\s*([:=])\s*[^\s,;]+")


def redact(text: str) -> str:
    return _SECRET.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)


class _Tee:
    def __init__(self, console, file):
        self.console = console
        self.file = file

    def write(self, text):
        self.console.write(text)
        self.file.write(redact(text))
        self.file.flush()

    def flush(self):
        self.console.flush()
        self.file.flush()


@contextmanager
def operation_log(operation: str):
    """Capture normal console evidence while redacting secret-shaped values."""
    stamp = datetime.now().strftime("%Y%m%d")
    path = log_path(f"{operation}_{stamp}")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n--- {operation} {datetime.now().isoformat(timespec='seconds')} ---\n")
        with redirect_stdout(_Tee(sys.stdout, handle)):
            yield str(path)
