"""The "Account & Browser" side of Samir Export - no window code, so it is testable.

Login: the person's own Knox / G-MES login goes into the engine's one credential
store (`gmes_credentials`, Windows DPAPI: readable only by this Windows account on
this PC). Nothing here prints, logs or returns a password.

Browser: the engine makes the automation's OWN copy of the person's Chrome or Edge
profile once, on the first connect (`gmes_browsers.ensure_bootstrapped`, read-only
towards the real profile), and records which browser it chose. Choosing a browser
here only sets the engine's own environment variables; switching to a browser other
than the one already recorded uses a separate profile folder and record beside the
first one - additive, nothing is deleted or re-copied over (CLAUDE.md 2.1, 2.1a).
"""
import os

import samir_env

samir_env.setup()

import cdp_common                     # noqa: E402
import gmes_browsers                  # noqa: E402
import gmes_credentials               # noqa: E402

CHOICES = ("auto", "chrome", "edge")
CHOICE_LABELS = {"auto": "Automatic - my Windows default browser",
                 "chrome": "Google Chrome", "edge": "Microsoft Edge"}
ENV_KEYS = ("GMES_BROWSER", "GMES_PROFILE_DIR", "GMES_BROWSER_STATE")
_ORIGINAL_ENV = {k: os.environ.get(k) for k in ENV_KEYS}


# --------------------------------------------------------------------------
# Browser choice
# --------------------------------------------------------------------------
def plan_browser_env(choice, recorded, root):
    """The engine variables for `choice`, as {name: value or None (= as found)}.

    `recorded` is the browser the standard setup already uses on this PC (None if
    none yet). Automatic, or the browser already recorded, keeps the standard
    profile. A different browser gets a profile and record of its own."""
    if choice not in CHOICES:
        raise ValueError(f"unknown browser choice {choice!r}")
    if choice == "auto":
        return {k: None for k in ENV_KEYS}
    if recorded in (None, choice):
        return {"GMES_BROWSER": choice, "GMES_PROFILE_DIR": None, "GMES_BROWSER_STATE": None}
    return {"GMES_BROWSER": choice,
            "GMES_PROFILE_DIR": os.path.join(root, "profiles", f"samir-{choice}"),
            "GMES_BROWSER_STATE": os.path.join(root, f"samir-browser-{choice}.json")}


def _restore_original_env():
    for key, value in _ORIGINAL_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def apply_browser_choice(choice):
    """Point the engine at the profile for `choice`. Returns the plan applied."""
    _restore_original_env()
    recorded = gmes_browsers.recorded_browser()
    plan = plan_browser_env(choice, recorded, gmes_browsers.AUTOMATION_ROOT)
    for key, value in plan.items():
        if value is not None:
            os.environ[key] = value
    return plan


def _profile_summary(p):
    return {"name": p.get("name") or p.get("dir"), "dir": p.get("dir"),
            "gmes": p.get("has_gmes_evidence"), "last_used": bool(p.get("last_used")),
            "has_session": bool(p.get("has_session"))}


def describe_browsers():
    """What this PC has, for the Account tab. Reads only; never raises."""
    info = {"default": None, "browsers": [], "state": {}, "same_machine": None,
            "profile_dir": "", "next_copy": None, "error": ""}
    try:
        info["default"] = gmes_browsers.default_browser_key()
        for key in gmes_browsers.SUPPORTED:
            exe = gmes_browsers.find_executable(key)
            profiles = []
            if exe:
                try:
                    profiles = [_profile_summary(p) for p in gmes_browsers.list_profiles(key)
                                if p.get("has_session")]
                except Exception:                           # noqa: BLE001 - display only
                    profiles = []
            info["browsers"].append({"key": key, "label": gmes_browsers.spec(key)["label"],
                                     "installed": bool(exe), "exe": exe or "",
                                     "profiles": profiles})
        state = gmes_browsers.read_state()
        info["state"] = state
        info["same_machine"] = (state.get("machine") == gmes_browsers.machine_id()) if state else None
        info["profile_dir"] = cdp_common.active_profile_dir()
        if not gmes_browsers.recorded_profile_dir():
            sources = gmes_browsers.candidate_sources()
            if sources:
                src = sources[0]
                info["next_copy"] = {"browser": src["browser"], "label": src["label"],
                                     "profile": src["profile"].get("name") or src["profile"].get("dir")}
    except Exception as e:                                  # noqa: BLE001 - display only
        info["error"] = f"{type(e).__name__}: {e}"
    return info


def setup_sentence(info):
    """One plain sentence about the automation's browser copy."""
    state = info.get("state") or {}
    if state.get("completed") and info.get("same_machine"):
        browser = gmes_browsers.BROWSERS.get(state.get("browser"), {}).get("label", state.get("browser"))
        how = {"copied": "copied once from your own profile",
               "existing": "an existing automation profile",
               "fresh": "an empty profile (signs in with your saved login)",
               "recorded": "set up earlier"}.get(state.get("strategy"), state.get("strategy") or "")
        src = (state.get("source") or {}).get("profile_name")
        when = state.get("onboarded_at") or ""
        return (f"Ready: uses {browser}, {how}" + (f" '{src}'" if src else "")
                + (f" on {when}" if when else "") + ".")
    nxt = info.get("next_copy")
    if nxt:
        return (f"Not set up yet. On the first Connect the tool makes its own copy of your "
                f"{nxt['label']} profile '{nxt['profile']}' - once, reading only.")
    return ("Not set up yet. No Chrome or Edge profile to copy was found, so the first Connect "
            "builds an empty profile and signs in with your saved login.")


# --------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------
def saved_login():
    """(user id or None, problem text or ''). The password is never returned."""
    user, password = gmes_credentials.load()
    del password
    return user, gmes_credentials.LAST_PROBLEM


def check_new_login(user, password, confirm):
    """Problems with what was typed, or []."""
    problems = []
    user = (user or "").strip()
    if not user:
        problems.append("Enter the Knox / G-MES user ID.")
    elif any(c.isspace() for c in user):
        problems.append("The user ID cannot contain spaces.")
    if not password:
        problems.append("Enter the password.")
    elif password != confirm:
        problems.append("The two passwords are not the same.")
    elif password != password.strip():
        problems.append("The password starts or ends with a space - check it was pasted correctly.")
    return problems


def save_login(user, password, confirm):
    """Validate, save, read back. Returns the saved user id; raises ValueError."""
    problems = check_new_login(user, password, confirm)
    if problems:
        raise ValueError("\n".join(problems))
    user = user.strip()
    gmes_credentials.save(user, password)
    back_user, back_password = gmes_credentials.load()
    ok = back_user == user and back_password == password
    del back_password
    if not ok:
        raise ValueError("The login was written but could not be read back: "
                         + (gmes_credentials.LAST_PROBLEM or "unknown reason"))
    return user


def store_location():
    return gmes_credentials.STORE_PATH


def windows_user():
    return os.environ.get("USERNAME") or "this Windows account"
