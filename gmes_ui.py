"""
Terminal presentation for the G-MES tools - colour, panels, and step lists.

Everything here degrades rather than breaks. Three separate things can be
missing on a corporate Windows machine, and each is detected rather than
assumed:

  * **ANSI colour.** A Windows console understands escape codes only after
    ENABLE_VIRTUAL_TERMINAL_PROCESSING is switched on. If that call fails,
    or the output is redirected to a file, every colour becomes an empty
    string and the layout still lines up, because colour is never used to
    carry meaning on its own.
  * **Box-drawing characters.** A console on code page 437 cannot encode
    them. They are tested against the real output encoding once, at import,
    and swapped for +-| if they would raise.
  * **A terminal at all.** Piped into a file or another program, the output
    stays plain.

Nothing here decides anything. It is presentation only, so a display fault
can never change what the automation does.
"""
import os
import shutil
import sys

WIDTH = min(78, max(60, shutil.get_terminal_size((80, 25)).columns - 2))


# ---------------------------------------------------------------------------
# Capability detection
# ---------------------------------------------------------------------------

def _enable_vt():
    """Turn on escape-code handling for this console. Windows only."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def _can_print(text):
    """Whether this console's encoding can actually render `text`."""
    try:
        text.encode(sys.stdout.encoding or "ascii")
        return True
    except (UnicodeEncodeError, LookupError, TypeError):
        return False


COLOUR = bool(getattr(sys.stdout, "isatty", lambda: False)()) and _enable_vt()
UNICODE = _can_print("─│╭╮╰╯✓✗▸•")


def _c(code):
    return f"\033[{code}m" if COLOUR else ""


DIM = _c("2")
BOLD = _c("1")
RESET = _c("0")
CYAN = _c("36")
BLUE = _c("94")
GREEN = _c("32")
YELLOW = _c("33")
RED = _c("31")
GREY = _c("90")
WHITE = _c("97")

if UNICODE:
    H, V, TL, TR, BL, BR = "─", "│", "╭", "╮", "╰", "╯"
    TICK, CROSS, ARROW, DOT, INFO, WARN = "✓", "✗", "▸", "·", "i", "!"
else:
    H, V, TL, TR, BL, BR = "-", "|", "+", "+", "+", "+"
    TICK, CROSS, ARROW, DOT, INFO, WARN = "OK", "X", ">", ".", "i", "!"


def visible_len(text):
    """Length as printed - escape codes take no space on screen."""
    out, i = 0, 0
    while i < len(text):
        if text[i] == "\033":
            while i < len(text) and text[i] != "m":
                i += 1
        else:
            out += 1
        i += 1
    return out


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

def rule(char=None):
    print(f"  {GREY}{(char or H) * (WIDTH - 4)}{RESET}")


def banner(title, subtitle="", accent=CYAN):
    inner = WIDTH - 4
    print()
    print(f"  {accent}{TL}{H * inner}{TR}{RESET}")
    _boxed(f"{BOLD}{WHITE}{title}{RESET}", accent, inner)
    if subtitle:
        _boxed(f"{GREY}{subtitle}{RESET}", accent, inner)
    print(f"  {accent}{BL}{H * inner}{BR}{RESET}")


def _boxed(text, accent, inner):
    pad = inner - 2 - visible_len(text)
    print(f"  {accent}{V}{RESET} {text}{' ' * max(0, pad)} {accent}{V}{RESET}")


def section(title):
    print()
    print(f"  {BOLD}{BLUE}{title.upper()}{RESET}")
    print(f"  {GREY}{H * min(len(title) + 6, WIDTH - 4)}{RESET}")


def field(label, value, width=14):
    print(f"    {GREY}{label:<{width}}{RESET}{WHITE}{value}{RESET}")


def bullet(text, mark=None, colour=None):
    print(f"    {colour or CYAN}{mark or ARROW}{RESET} {text}")


def note(text, kind="info"):
    colour = {"info": CYAN, "warn": YELLOW, "bad": RED}.get(kind, CYAN)
    mark = {"info": INFO, "warn": WARN, "bad": CROSS}.get(kind, INFO)
    print(f"      {colour}[{mark}]{RESET} {GREY}{text}{RESET}")


def step(number, label, detail, ok=True, seconds=None):
    """One numbered step: a tick, the label, leaders, then what happened.

    The detail is put on its own line when it will not fit, rather than
    wrapping into the leader dots and turning the column into noise."""
    mark = f"{GREEN}{TICK}{RESET}" if ok else f"{RED}{CROSS}{RESET}"
    stamp = f" {GREY}{seconds:>5.1f}s{RESET}" if seconds is not None else ""
    head = f"    {mark} {GREY}{number:>2}{RESET}  {WHITE}{label}{RESET}"
    used = visible_len(head) + visible_len(stamp)
    room = WIDTH - used - 4
    if len(detail) <= room:
        dots = f"{GREY}{DOT * max(2, room - len(detail))}{RESET}"
        print(f"{head} {dots} {detail}{stamp}")
    else:
        print(f"{head} {GREY}{DOT * max(2, room)}{RESET}{stamp}")
        print(f"          {GREY}{detail}{RESET}")


def result(ok, title, lines=()):
    accent = GREEN if ok else RED
    banner(title, accent=accent)
    for line in lines:
        print(f"    {line}")


def phase(recording, screen, learned=""):
    """The record/replay banner - the one thing a viewer must not miss."""
    if recording:
        banner(f"RECORDING  {DOT}  {screen} is new",
               "It will work the screen out as it goes, and remember it "
               "if the run succeeds.", accent=YELLOW)
    else:
        banner(f"REPLAYING  {DOT}  {screen} was learned {learned}",
               "It will check the screen still matches, then reuse what it "
               "knows.", accent=GREEN)
