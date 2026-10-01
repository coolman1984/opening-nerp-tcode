"""The window's own settings (data/settings.json): browser choice, row-export form,
appearance (theme, font, text size) and where the person dragged each divider.

Nothing here is a secret - the login lives in the DPAPI store, never in this file.
"""
import json
import os
import threading

import app_env

_lock = threading.Lock()


def settings_file():
    return os.path.join(app_env.data_dir(), "settings.json")


def load():
    try:
        with open(settings_file(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(**values):
    """Merge `values` into the file. Written to a side file and swapped in, so a crash
    or a full disk mid-write leaves the old settings instead of an empty file (the old
    direct write could lose the browser choice and every saved form at once)."""
    with _lock:
        data = load()
        data.update(values)
        path = settings_file()
        tmp = path + ".tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass


def appearance():
    value = load().get("appearance")
    return value if isinstance(value, dict) else {}


def pane(name):
    value = load().get("panes", {})
    return value.get(name) if isinstance(value, dict) else None


def set_pane(name, fraction):
    panes = load().get("panes")
    panes = dict(panes) if isinstance(panes, dict) else {}
    if fraction is None:
        panes.pop(name, None)
    else:
        panes[name] = fraction
    save(panes=panes)
