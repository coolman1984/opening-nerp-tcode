"""Chrome discovery, profile-copy and process lifecycle for standalone G-MES.

Forked from cdp_common.py (see browser/cdp.py's module docstring for why).
Only the chrome-launch functions G-MES's own code actually calls are
copied - N-ERP's disposable-profile launcher (`launch_chrome`) and its
temp-profile helper (`profile_dir`) are NOT included here: grepping every
gmes_*.py file's cdp_common usage found no call to either, and G-MES's own
design (a persistent, never-deleted profile copy, HISTORY.md Phase 4.1) is
the opposite of N-ERP's throwaway-profile-per-run approach that those two
functions exist for.
"""
import os
import shutil
import subprocess
import time

from .cdp import CDP_PORT, cdp_is_up

# The Popen handle for the Chrome this process started, so a caller can shut
# down exactly that instance instead of taskkilling every chrome.exe.
LAST_CHROME_PROCESS = None

# Floor on how long a single browser/profile combination is given to open its
# debugging port, when more than one is being tried. A module-level constant
# rather than a literal so an offline test can shrink it instead of a real
# multi-second wait per failing attempt.
_MIN_ATTEMPT_WAIT = 15


def find_chrome():
    """Locate chrome.exe without hardcoding one install path - a per-user
    install lands under %LOCALAPPDATA% instead of Program Files."""
    override = os.environ.get("CHROME_PATH")
    if override and os.path.isfile(override):
        return override

    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     r"Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path

    found = shutil.which("chrome") or shutil.which("chrome.exe")
    if found:
        return found

    try:  # registry is authoritative when Chrome is installed oddly
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(
                    root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe")
                path, _ = winreg.QueryValueEx(key, "")
                if path and os.path.isfile(path):
                    return path
            except OSError:
                continue
    except ImportError:
        pass

    raise RuntimeError(
        "Could not find chrome.exe. Set the CHROME_PATH environment variable "
        "to its full path and retry.")


def find_edge():
    """Locate msedge.exe. Edge is Chromium, and speaks the same DevTools
    protocol with the same command-line flags, so everything this package
    does works against it unchanged.

    It matters because Edge is present on a managed Windows build whether or
    not anyone installed Chrome. A machine in the factory with no Chrome is
    not a machine this program cannot run on."""
    override = os.environ.get("EDGE_PATH")
    if override and os.path.isfile(override):
        return override

    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     r"Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path

    found = shutil.which("msedge") or shutil.which("msedge.exe")
    if found:
        return found

    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(
                    root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe")
                path, _ = winreg.QueryValueEx(key, "")
                if path and os.path.isfile(path):
                    return path
            except OSError:
                continue
    except ImportError:
        pass
    return None


def find_browser():
    """The browser to drive: Chrome when it is installed, else Edge.

    Returns (path, name). Chrome stays first because every observed
    behaviour in this project - and every gotcha in GMES_SKILL.md - was
    established against it. Edge is the fallback rather than an equal
    choice, so a machine with both behaves exactly as this one does."""
    try:
        return find_chrome(), "Chrome"
    except RuntimeError as missing:
        edge = find_edge()
        if edge:
            return edge, "Edge"
        raise RuntimeError(
            f"{missing} Microsoft Edge was not found either - set CHROME_PATH "
            "or EDGE_PATH to a Chromium browser's .exe and retry.") from missing


def default_user_profile_dir():
    """The real Chrome profile - the one with the user's logins, extensions
    and certificates. G-MES needs the real profile's extensions/logins,
    unlike N-ERP's throwaway one."""
    override = os.environ.get("CHROME_USER_DATA_DIR")
    if override:
        return override
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data")


def chrome_is_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
                             capture_output=True, text=True, timeout=15)
        return "chrome.exe" in (out.stdout or "")
    except Exception:
        return False


def working_profile_dir():
    """Where the debuggable copy of the user's profile lives. Left at its
    existing Chrome-owned location. It is a copy of the user's Default
    profile, never the real profile itself, and retains the authorized
    Chrome/session behavior expected by existing G-MES automation."""
    override = os.environ.get("CHROME_CDP_PROFILE_DIR")
    if override:
        return override
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "CDP Profile")


# Caches are large, regenerate themselves, and carry nothing we need.
_PROFILE_SKIP_DIRS = [
    "Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache",
    "DawnWebGPUCache", "GrShaderCache", "ShaderCache", "Media Cache",
    "component_crx_cache", "extensions_crx_cache", "Crashpad",
    "Safe Browsing", "optimization_guide_model_store",
]


def clone_user_profile(dest=None, refresh=False, verbose=True):
    """Copy the real Chrome profile to a directory we are allowed to debug.

    Chrome 136+ silently ignores --remote-debugging-port whenever
    --user-data-dir points at the default profile directory (a deliberate
    security fix). The supported way around it is to debug a copy, which
    also keeps extensions, cookies and saved logins intact. Session-only
    cookies do not survive, so a site may ask to sign in once inside the
    copy.

    Copying is skipped when the destination already exists, unless refresh
    is set - re-copying on every run would be slow and would throw away the
    signed-in state built up inside the copy."""
    src = default_user_profile_dir()
    dest = dest or working_profile_dir()

    if not os.path.isdir(src):
        raise RuntimeError(f"Could not find the Chrome profile at {src!r}. "
                           "Set CHROME_USER_DATA_DIR to its location.")

    if os.path.isdir(dest) and not refresh:
        if verbose:
            print(f"Using the existing debuggable profile copy: {dest}")
        return dest

    if verbose:
        print(f"Copying your Chrome profile (this happens once, ~1 minute):")
        print(f"  from {src}")
        print(f"  to   {dest}")

    cmd = ["robocopy", src, dest, "/E", "/R:0", "/W:0",
           "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/XJ",
           "/XD"] + list(_PROFILE_SKIP_DIRS)
    result = subprocess.run(cmd, capture_output=True, text=True)
    # robocopy uses exit codes as a bitmask; 0-7 are success, 8+ are errors.
    if result.returncode >= 8:
        raise RuntimeError(
            f"Copying the profile failed (robocopy exit {result.returncode}). "
            f"{(result.stdout or '').strip()[-400:]}")
    if verbose:
        print("Profile copy ready.")
    return dest


def automation_profile(refresh=False, verbose=True):
    """Which profile directory to debug, and a sentence naming it.

    Two strategies, and which one applies is decided by what is already on
    the machine rather than by a setting somebody has to know about:

    * **The copy.** A debuggable copy of the operator's own Chrome profile,
      carrying their session and saved logins. This is what the developer's
      machine has used since Phase 4.1, and while that copy exists it stays
      in use, untouched (CLAUDE.md 2.1a).
    * **A clean profile.** Program-owned, created empty by the browser
      itself. This is what a colleague's machine gets.

    The clean profile is the default for everyone else on purpose. Copying
    somebody's personal Chrome profile takes their own accounts and
    passwords with it, takes about a minute, and buys nothing: they have
    their own G-MES credentials, and signing in with those puts the session
    in the clean profile where the next run finds it.

    `GMES_BROWSER_PROFILE=copy|clean` forces one. Nothing here ever deletes
    a profile; `refresh` re-copies over the copy and is only ever reached
    because a person asked for it in that run.
    """
    from ..paths import browser_profile_dir

    choice = (os.environ.get("GMES_BROWSER_PROFILE") or "").strip().casefold()
    if refresh or choice == "copy":
        return clone_user_profile(refresh=refresh, verbose=verbose), \
            "a copy of your own Chrome profile"
    if choice != "clean" and os.path.isdir(working_profile_dir()):
        # Already there: clone_user_profile returns it without copying.
        return clone_user_profile(verbose=verbose), \
            "the existing copy of your Chrome profile"
    profile = str(browser_profile_dir())
    if verbose:
        print(f"Using this program's own clean browser profile: {profile}")
    return profile, "a clean profile owned by this program"


def _wait_for_port(port, timeout, poll=0.5):
    """Poll until the debugging port answers, or the timeout runs out.

    Pulled out on its own so a test can decide whether one attempt "worked"
    without controlling the wall clock through time.time() and time.sleep -
    both of which several attempts in sequence would otherwise need to
    fake in lockstep."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cdp_is_up(port):
            return True
        time.sleep(poll)
    return False


def _launch_attempts(refresh_profile):
    """Every (name, browser_path, profile_dir, how) worth trying, in order.

    `automation_profile()`'s single choice comes first, unchanged - the
    common case is one browser, one profile, no fallback needed, exactly as
    it has always worked. What follows exists only for when that fails to
    open its debugging port at all: a profile copy can be corrupted or
    locked by a crashed previous run, and a Chrome install can be present on
    disk but unable to start. Neither stops the run today; each gets a
    different combination to try instead.

    A refresh is never retried under a different combination - it was asked
    for explicitly, on the one profile it names, and silently trying
    something else in its place would answer a different question than the
    one that was asked."""
    from ..paths import browser_profile_dir

    clean = str(browser_profile_dir())

    if refresh_profile:
        profile, how = automation_profile(refresh=True, verbose=False)
        return [("Chrome", find_chrome, profile, how)]

    attempts = []
    try:
        find_chrome()       # is Chrome even installed, regardless of profile?
    except RuntimeError:
        pass                # no Chrome attempt is worth building at all
    else:
        try:
            primary_profile, how = automation_profile(verbose=False)
        except RuntimeError:
            primary_profile, how = clean, "a clean profile owned by this program"
        attempts.append(("Chrome", find_chrome, primary_profile, how))
        if primary_profile != clean:
            attempts.append(("Chrome", find_chrome, clean,
                             "a clean profile owned by this program (fallback)"))

    if find_edge() is not None:
        attempts.append(("Edge", find_edge, clean,
                         "a clean profile owned by this program"))
    return attempts


def launch_chrome_with_user_profile(port=None, url=None, wait_seconds=45,
                                    refresh_profile=False):
    """Start the automation browser, trying more than one way if it will not
    come up cleanly.

    Named for the copy-the-user's-profile strategy it originally had, and
    kept under that name because it is the entrance every caller already
    uses. `_launch_attempts()` now decides what to try, in order: the
    profile `automation_profile()` would already choose, then a clean
    profile if that is a different one, then Edge - so a profile copy that
    will not open, or a Chrome that will not start at all, does not end the
    run when a working alternative is one attempt away.

    Never deletes or modifies the real profile - see clone_user_profile.
    Chrome will not open a second browser process on a profile already in
    use, so the caller must make sure Chrome is closed first when
    refresh_profile=True (refreshing needs the real profile's files
    unlocked to copy them)."""
    port = port or CDP_PORT
    if cdp_is_up(port):
        return None  # already listening; reuse it

    attempts = _launch_attempts(refresh_profile)
    if not attempts:
        raise RuntimeError(
            "Could not find Chrome or Edge. Set CHROME_PATH or EDGE_PATH to a "
            "Chromium browser's .exe and retry.")

    per_attempt = wait_seconds if len(attempts) == 1 else max(_MIN_ATTEMPT_WAIT, wait_seconds // len(attempts))
    failures = []
    global LAST_CHROME_PROCESS
    for index, (name, locate, profile, how) in enumerate(attempts):
        try:
            browser = locate()
        except RuntimeError as error:
            failures.append(f"{name}: {error}")
            continue
        print(f"Browser: {name} on {how}")
        args = [browser, f"--remote-debugging-port={port}",
                f"--user-data-dir={profile}",
                "--profile-directory=Default",
                "--remote-allow-origins=*",
                "--no-first-run", "--no-default-browser-check",
                "--restore-last-session=false"]
        if url:
            args.append(url)

        LAST_CHROME_PROCESS = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if _wait_for_port(port, per_attempt):
            return LAST_CHROME_PROCESS

        # This attempt never opened the port. Stop it before trying the next
        # one - two processes on the same debugging port would only make the
        # next attempt's failure ambiguous.
        failures.append(f"{name} on {how} never opened port {port}")
        try:
            LAST_CHROME_PROCESS.terminate()
            LAST_CHROME_PROCESS.wait(timeout=5)
        except Exception:
            pass
        if index < len(attempts) - 1:
            print(f"  ({failures[-1]} - trying the next option)")

    raise RuntimeError(
        f"No browser opened the debugging port {port} after "
        f"{len(attempts)} attempt(s): " + "; ".join(failures))


def close_browser(port=None, timeout=15):
    """Close the automation browser, and only that one - through its own
    DevTools endpoint, never `taskkill /IM chrome.exe`, which would take
    every Chrome window the user has open (CLAUDE.md 2.6). Returns True
    once the port has actually gone."""
    # Local imports to avoid a hard circular dependency between cdp.py
    # (transport) and chrome.py (process lifecycle) at module-load time.
    from .cdp import CDP_HOST, connect, ipv4, send
    import json
    import urllib.request

    port = port or CDP_PORT
    if not cdp_is_up(port):
        return True
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://{CDP_HOST}:{port}/json/version", timeout=5) as response:
            info = json.loads(response.read().decode())
        ws = connect(ipv4(info["webSocketDebuggerUrl"]), enable_runtime=False)
        try:
            send(ws, "Browser.close", timeout=5)
        finally:
            try:
                ws.close()
            except Exception:
                pass
    except Exception:
        pass        # it may have gone on its own between the check and the call

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not cdp_is_up(port):
            return True
        time.sleep(0.5)
    return False
