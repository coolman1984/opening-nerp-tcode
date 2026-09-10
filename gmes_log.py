"""
A complete record of what a run actually did, on disk, for afterwards.

    logs/gmes_20260910.log          one file per day, appended

Every session writes: the version and command line, every question and the
answer given, every step the automation reported, every warning, and the full
traceback of anything that failed. When something goes wrong at 02:00 - or
five minutes ago in a window that has since been closed - this is what there
is to read.

Why a tee rather than a logging framework
-----------------------------------------
Everything of interest is already printed. Mirroring stdout captures the
sign-in, the questions, the numbered steps and the summary in the order they
happened, with nothing to keep in step by hand - a separate log call beside
every print is a log that goes stale the first time someone forgets one.

Two things are handled that a plain tee would get wrong:

  * **Colour codes are stripped** on the way to the file. A log full of
    `\033[36m` is a log nobody reads.
  * **The password is never here**, because it is never printed - the sign-in
    reports the user id and nothing else (CLAUDE.md 2.2). Neither are session
    tokens: dataset dumps go nowhere near stdout (2.3).

`logs/` is git-ignored. A filter value can be a production order number, and
row counts are production data.
"""
import os
import re
import sys
import time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")

_ANSI = re.compile(r"\033\[[0-9;]*m")
_handle = None
_path = None


def path():
    return _path


class _Tee:
    """Writes to the real console and to the log file, colour-free."""

    def __init__(self, stream, handle):
        self._stream = stream
        self._handle = handle
        self._at_line_start = True

    def write(self, text):
        self._stream.write(text)
        try:
            plain = _ANSI.sub("", text)
            for piece in plain.splitlines(keepends=True):
                if self._at_line_start and piece.strip():
                    self._handle.write(time.strftime("%H:%M:%S  "))
                self._handle.write(piece)
                self._at_line_start = piece.endswith("\n")
            self._handle.flush()
        except Exception:
            pass          # a logging fault must never break the tool itself

    def flush(self):
        self._stream.flush()
        try:
            self._handle.flush()
        except Exception:
            pass

    def isatty(self):
        # Asked by gmes_ui to decide on colour. The answer must describe the
        # CONSOLE, not the log file, or wrapping stdout would silently turn
        # the colours off.
        return getattr(self._stream, "isatty", lambda: False)()

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", "utf-8")


def start(what="session"):
    """Begin mirroring stdout into today's log. Returns the file path."""
    global _handle, _path
    if _handle is not None:
        return _path
    os.makedirs(LOG_DIR, exist_ok=True)
    _path = os.path.join(LOG_DIR, f"gmes_{datetime.now():%Y%m%d}.log")
    _handle = open(_path, "a", encoding="utf-8")
    _handle.write("\n" + "=" * 78 + "\n")
    _handle.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {what}\n")
    _handle.write(f"  command    : {' '.join(sys.argv)}\n")
    _handle.write(f"  python     : {sys.version.split()[0]}\n")
    _handle.write(f"  working dir: {os.getcwd()}\n")
    _handle.write("=" * 78 + "\n")
    _handle.flush()
    sys.stdout = _Tee(sys.stdout, _handle)
    return _path


def note(text):
    """Write something to the log only - not to the console."""
    if _handle is None:
        return
    try:
        _handle.write(f"{time.strftime('%H:%M:%S')}  . {text}\n")
        _handle.flush()
    except Exception:
        pass


def failure(exc):
    """Record a full traceback. The console gets one readable sentence; this
    is where the detail that actually identifies the fault lives."""
    import traceback
    note("EXCEPTION " + "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip())


def finish(summary=""):
    global _handle
    if _handle is None:
        return
    try:
        if summary:
            _handle.write(f"{time.strftime('%H:%M:%S')}  = {summary}\n")
        _handle.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  session ended\n")
        _handle.flush()
    except Exception:
        pass
