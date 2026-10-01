"""The window's themes, fonts and text sizes - data only, so it is tested on its own.

Every colour the page paints is a token of a theme (sent to the page as CSS
variables). Each theme is checked for WCAG AA contrast by the tests.
"""
_LIGHT = {
    "bg": "#EEF2F7", "card": "#FFFFFF", "border": "#DCE3EC", "line": "#E8EDF3",
    "text": "#0F172A", "muted": "#5B6B82", "faint": "#94A3B8",
    "header": "#0B1B3F", "header2": "#16306B", "header_text": "#E6ECF7", "header_muted": "#9FB0D0",
    "nav_hover": "#132A5C", "nav_bar": "#60A5FA", "nav_group": "#5E74A3", "nav_badge": "#FCA5A5",
    "accent": "#2563EB", "accent_hover": "#1D4ED8", "accent_soft": "#E8F0FE", "logo2": "#3B82F6",
    "on_accent": "#FFFFFF",
    "ok": "#15803D", "ok_hover": "#166534", "ok_soft": "#DCFCE7", "ok_text": "#166534",
    "warn": "#B45309", "warn_soft": "#FEF3C7", "warn_text": "#92400E",
    "err": "#DC2626", "err_hover": "#B91C1C", "err_soft": "#FEE2E2", "err_text": "#991B1B",
    "dark": "#7F1D1D", "dark_hover": "#5F1515",
    "disabled_bg": "#E6EBF2", "disabled_fg": "#A3AFC0",
    "tile": "#F7F9FC", "field": "#FFFFFF", "raised": "#FFFFFF", "raised_hover": "#F1F5F9",
    "thumb": "#C5CFDC", "thumb_hover": "#A7B4C6",
    "console": "#0B1220", "console_text": "#CBD5E1", "console_sel": "#27406E",
    "console_thumb": "#2A3549", "console_thumb_hover": "#3A4A66",
    "log_time": "#56657E", "log_info": "#DCE4F0", "log_muted": "#7D8BA3",
    "log_ok": "#4ADE80", "log_warn": "#FBBF24", "log_err": "#F87171",
}
_DARK = dict(_LIGHT, **{
    "bg": "#0F172A", "card": "#1E293B", "border": "#334155", "line": "#2B3A50",
    "text": "#E2E8F0", "muted": "#94A3B8", "faint": "#64748B",
    "header": "#0A1020", "header2": "#1E2A4A", "header_text": "#CBD5E1", "header_muted": "#7C8CA8",
    "nav_hover": "#141D33", "nav_group": "#4F5F80",
    "accent": "#60A5FA", "accent_hover": "#93C5FD", "accent_soft": "#1B3150", "logo2": "#3B82F6",
    "on_accent": "#0B1220",
    "ok": "#15803D", "ok_hover": "#166534", "ok_soft": "#14321F", "ok_text": "#4ADE80",
    "warn": "#D97706", "warn_soft": "#3A2A10", "warn_text": "#FBBF24",
    "err": "#DC2626", "err_hover": "#B91C1C", "err_soft": "#3B1717", "err_text": "#F87171",
    "disabled_bg": "#273449", "disabled_fg": "#5B6B82",
    "tile": "#172235", "field": "#0F1A2E", "raised": "#253349", "raised_hover": "#2E3E58",
    "thumb": "#3A4A63", "thumb_hover": "#4B5D7A",
    "console": "#060B16", "console_thumb": "#1F2A3D", "console_thumb_hover": "#2E3D57",
})
THEMES = {
    "Light": _LIGHT,
    "Dark": _DARK,
    "Ocean": dict(_LIGHT, **{
        "bg": "#E9F3F3", "border": "#CFE3E3", "line": "#E1EEEE", "text": "#0B2A2E",
        "muted": "#4E6B6F", "faint": "#8FA8AB",
        "header": "#053B40", "header2": "#0B5C63", "header_text": "#DDF3F2", "header_muted": "#8FC2C0",
        "nav_hover": "#084950", "nav_bar": "#5EEAD4", "nav_group": "#4E8C8A",
        "accent": "#0B6E77", "accent_hover": "#095A61", "accent_soft": "#E0F2F2", "logo2": "#14B8A6",
        "tile": "#F4FAFA", "raised_hover": "#EEF6F6", "disabled_bg": "#E2ECEC",
        "thumb": "#BDD6D6", "thumb_hover": "#9CC2C2",
        "console": "#04252A", "console_text": "#C8E3E1", "console_sel": "#145057",
        "console_thumb": "#16444A", "console_thumb_hover": "#1F5A61",
    }),
    "Graphite": dict(_LIGHT, **{
        "bg": "#F0F1F3", "border": "#DADDE2", "line": "#E7E9EC", "text": "#18181B",
        "muted": "#5F6370", "faint": "#9CA0AA",
        "header": "#1C1D21", "header2": "#2F3138", "header_text": "#E7E8EA", "header_muted": "#9A9DA6",
        "nav_hover": "#26272C", "nav_bar": "#A5B4FC", "nav_group": "#6B6E78",
        "accent": "#4F46E5", "accent_hover": "#4338CA", "accent_soft": "#ECEBFD", "logo2": "#818CF8",
        "tile": "#F7F7F8", "raised_hover": "#F2F2F4", "disabled_bg": "#E8E9EC",
        "thumb": "#C9CCD2", "thumb_hover": "#ABAFB8",
        "console": "#141518", "console_text": "#D4D4D8", "console_sel": "#3A3A55",
        "console_thumb": "#2C2D33", "console_thumb_hover": "#3D3F47",
    }),
    "Sand": dict(_LIGHT, **{
        "bg": "#F5EFE6", "card": "#FFFDF9", "border": "#E6DCCB", "line": "#EFE7DA", "text": "#2B2118",
        "muted": "#6E5E4C", "faint": "#A8977F",
        "header": "#3B2A1A", "header2": "#5A4029", "header_text": "#F4E9DA", "header_muted": "#C2AD92",
        "nav_hover": "#4A3522", "nav_bar": "#F6AD55", "nav_group": "#9C8468",
        "accent": "#A44A18", "accent_hover": "#863A10", "accent_soft": "#FBE9DC", "logo2": "#DD7A3C",
        "tile": "#FBF7F0", "field": "#FFFEFB", "raised": "#FFFEFB", "raised_hover": "#F7F0E6",
        "disabled_bg": "#EEE6DA", "disabled_fg": "#A3937D", "thumb": "#D9CCB8", "thumb_hover": "#C4B297",
        "console": "#22180F", "console_text": "#E8DCCB", "console_sel": "#5A4029",
        "console_thumb": "#3A2C1F", "console_thumb_hover": "#4E3B2A",
    }),
    "Midnight": dict(_DARK, **{
        "bg": "#0B1014", "card": "#121A21", "border": "#24323D", "line": "#1C2731",
        "text": "#E3EAF0", "muted": "#8DA0AF", "faint": "#5E7180",
        "header": "#070B0E", "header2": "#13303A", "header_text": "#CFE0E8", "header_muted": "#6F8794",
        "nav_hover": "#0E1A20", "nav_bar": "#2DD4BF", "nav_group": "#4C6370",
        "accent": "#2DD4BF", "accent_hover": "#5EEAD4", "accent_soft": "#0F2F31", "logo2": "#0D9488",
        "on_accent": "#042F2E",
        "tile": "#0F171D", "field": "#0B1318", "raised": "#1A2530", "raised_hover": "#22303C",
        "disabled_bg": "#1B262F", "disabled_fg": "#4E606C",
        "thumb": "#2A3946", "thumb_hover": "#3A4D5D",
        "console": "#05080A", "console_sel": "#13303A",
        "console_thumb": "#18232B", "console_thumb_hover": "#24343F",
    }),
}
DEFAULT_THEME = "Light"
C = dict(_LIGHT)

# Fonts offered in Appearance, best first; only the ones installed on the PC are shown.
UI_FONTS = ("Segoe UI", "Segoe UI Variable Text", "Aptos", "Bahnschrift", "Calibri", "Candara",
            "Corbel", "Trebuchet MS", "Verdana", "Tahoma", "Georgia")
MONO_FONTS = ("Cascadia Mono", "Cascadia Code", "Consolas", "Lucida Console", "Courier New")
TEXT_SIZES = (90, 100, 110, 125, 140)        # percent
APPEARANCE_DEFAULTS = {"theme": DEFAULT_THEME, "font": "Segoe UI", "mono": "Consolas", "size": 100}


def resolve_appearance(saved, families):
    """The appearance to use: what the person chose, with anything this PC cannot show
    (a theme that no longer exists, a font that is not installed, a size off the list)
    replaced by the nearest thing that works - never an error at start-up."""
    want = dict(APPEARANCE_DEFAULTS)
    want.update(saved if isinstance(saved, dict) else {})
    for key in ("theme", "font", "mono"):            # a hand-edited file may hold anything
        if not isinstance(want[key], str):
            want[key] = APPEARANCE_DEFAULTS[key]
    families = set(families)
    theme = want["theme"] if want["theme"] in THEMES else DEFAULT_THEME
    fonts = [f for f in UI_FONTS if f in families]
    font = want["font"] if want["font"] in fonts else (fonts[0] if fonts else "system-ui")
    monos = [f for f in MONO_FONTS if f in families]
    mono = want["mono"] if want["mono"] in monos else (monos[0] if monos else "monospace")
    try:
        size = int(want["size"])
    except (TypeError, ValueError):
        size = 100
    size = min(TEXT_SIZES, key=lambda s: abs(s - size))
    return {"theme": theme, "font": font, "mono": mono, "size": size}


# The family a font's files are registered under in Windows, when it differs from the
# name a page uses for it ("Segoe UI Variable Text" is one face of "Segoe UI Variable").
_REGISTRY_NAME = {"Segoe UI Variable Text": "Segoe UI Variable"}


def installed_families():
    """The offered fonts that are installed on this PC (for every user or only this
    one), read from the Windows font registry. Never raises: no list means only the
    defaults are offered."""
    try:
        import winreg
    except ImportError:
        return set()
    names = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
        except OSError:
            continue
        with key:
            i = 0
            while True:
                try:
                    names.append(winreg.EnumValue(key, i)[0].lower())
                except OSError:
                    break
                i += 1
    # A value name is "<family>[ <style>] (TrueType)" or "<family> & <family> (TrueType)".
    faces = set()
    for n in names:
        base = n.split(" (")[0]
        faces.update(part.strip() for part in base.split(" & "))
    found = set()
    for family in UI_FONTS + MONO_FONTS:
        reg = _REGISTRY_NAME.get(family, family).lower()
        if reg in faces or f"{reg} regular" in faces:
            found.add(family)
    return found
