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


def default_user_profile_dir():
    """The real Chrome profile - the one with the user's logins, extensions
    and certificates. G-MES needs the real profile's extensions/logins,
    unlike N-ERP's throwaway one."""
    override = os.environ.get("CHROME_USER_DATA_DIR")
    if override:
        return override
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\User Data")


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
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\CDP Profile")


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


def launch_chrome_with_user_profile(port=None, url=None, wait_seconds=45,
                                    refresh_profile=False):
    """Start Chrome on a debuggable COPY of the user's own profile.

    Never deletes or modifies the real profile - see clone_user_profile.
    Chrome will not open a second browser process on a profile already in
    use, so the caller must make sure Chrome is closed first when
    refresh_profile=True (refreshing needs the real profile's files
    unlocked to copy them)."""
    port = port or CDP_PORT
    if cdp_is_up(port):
        return None  # already listening; reuse it

    profile = clone_user_profile(refresh=refresh_profile)
    chrome = find_chrome()
    args = [chrome, f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--profile-directory=Default",
            "--remote-allow-origins=*",
            "--no-first-run", "--no-default-browser-check",
            "--restore-last-session=false"]
    if url:
        args.append(url)

    global LAST_CHROME_PROCESS
    LAST_CHROME_PROCESS = subprocess.Popen(
        args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if cdp_is_up(port):
            return LAST_CHROME_PROCESS
        time.sleep(0.5)

    raise RuntimeError(
        f"Chrome started but never opened the debugging port {port}. Usual "
        "causes: another Chrome window is still open (check the system tray), "
        f"or the profile copy at {profile!r} is in use by another instance.")


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
