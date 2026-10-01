"""Look and feel of GMES Automation: colours, fonts, and the few widgets tkinter lacks
(flat buttons, cards, a segmented control, stat tiles, a scrolling column, dialogs).

Standard library only - the .exe must run on a locked-down PC with nothing installed.
"""
import ctypes
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# --------------------------------------------------------------------------
# Themes. Every colour the window paints comes from C; a theme is a full set of
# these tokens, so switching one repaints everything once the window is rebuilt.
# --------------------------------------------------------------------------
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

SCALE = 1.0


def S(n):
    """Pixels, scaled to the screen's DPI."""
    return max(1, int(round(n * SCALE)))


def make_dpi_aware():
    """Sharp text on 125 % / 150 % laptop screens instead of a blurred bitmap."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:                                       # noqa: BLE001 - older Windows
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:                                   # noqa: BLE001
            pass


F = {}
APPEARANCE = dict(APPEARANCE_DEFAULTS)


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
    font = want["font"] if want["font"] in fonts else (fonts[0] if fonts else "TkDefaultFont")
    monos = [f for f in MONO_FONTS if f in families]
    mono = want["mono"] if want["mono"] in monos else (monos[0] if monos else "TkFixedFont")
    try:
        size = int(want["size"])
    except (TypeError, ValueError):
        size = 100
    size = min(TEXT_SIZES, key=lambda s: abs(s - size))
    return {"theme": theme, "font": font, "mono": mono, "size": size}


def semibold(family, size, families):
    """A semibold face of `family` when the PC has one, else its bold weight."""
    for name in (family + " Semibold", family + " SemiBold"):
        if name in families:
            return (name, size)
    return (family, size, "bold")


def installed_fonts(root):
    families = set(tkfont.families(root))
    return ([f for f in UI_FONTS if f in families], [f for f in MONO_FONTS if f in families])


def setup_theme(root, appearance=None):
    """Colours, fonts, ttk styles and the DPI scale. Call right after Tk(), and again
    (then rebuild every widget) when the person changes the appearance."""
    global SCALE
    SCALE = max(1.0, root.winfo_fpixels("1i") / 96.0)
    families = set(tkfont.families(root))
    APPEARANCE.clear()
    APPEARANCE.update(resolve_appearance(appearance, families))
    C.clear()
    C.update(THEMES[APPEARANCE["theme"]])
    FlatButton.refresh_kinds()
    family, pct = APPEARANCE["font"], APPEARANCE["size"] / 100.0

    def pt(n):
        return max(7, int(round(n * pct)))

    def semi(n):
        return semibold(family, pt(n), families)
    F.update({
        "body": (family, pt(10)), "small": (family, pt(9)), "tiny": (family, pt(8)),
        "label": semi(9), "button": semi(10), "button_lg": semi(11), "field_lg": semi(11),
        "card_title": semi(11), "title": semi(16), "subtitle": (family, pt(9)),
        "tab": semi(10), "stat": semi(19), "status": semi(13), "brand": semi(15),
        "mono": (APPEARANCE["mono"], pt(9)), "badge": semi(9),
        "glyph": ("Segoe UI Symbol", pt(12)),
    })
    root.option_add("*Font", F["body"])
    # A plain label that names no colour must still be readable on a dark theme.
    root.option_add("*Foreground", C["text"])
    root.option_add("*Background", C["card"])
    root.option_add("*TCombobox*Listbox.font", F["body"])
    root.option_add("*TCombobox*Listbox.background", C["field"])
    root.option_add("*TCombobox*Listbox.foreground", C["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", C["on_accent"])

    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure(".", font=F["body"], background=C["card"], foreground=C["text"],
                 bordercolor=C["border"], focuscolor=C["accent"])
    field = dict(fieldbackground=C["field"], background=C["field"], foreground=C["text"],
                 bordercolor=C["border"], lightcolor=C["border"], darkcolor=C["border"],
                 insertcolor=C["text"], padding=(S(8), S(5)), arrowcolor=C["muted"],
                 selectbackground=C["accent_soft"], selectforeground=C["text"])
    focus = [("focus", C["accent"])]
    for name in ("TEntry", "TCombobox", "TSpinbox"):
        st.configure(name, **field)
        st.map(name, bordercolor=focus, lightcolor=focus, darkcolor=focus,
               fieldbackground=[("readonly", C["field"]), ("disabled", C["tile"])],
               foreground=[("disabled", C["faint"])],
               selectbackground=[("readonly", C["field"])], selectforeground=[("readonly", C["text"])])
    st.configure("TSpinbox", arrowsize=S(11))
    st.configure("TCombobox", arrowsize=S(13))
    for name in ("TCheckbutton", "TRadiobutton"):
        st.configure(name, background=C["card"], foreground=C["text"], padding=(0, S(3)),
                     indicatorbackground=C["field"], indicatorforeground=C["on_accent"],
                     upperbordercolor=C["faint"], lowerbordercolor=C["faint"],
                     indicatormargin=(0, 0, S(8), 0), indicatorsize=S(14), focuscolor=C["card"])
        st.map(name, indicatorbackground=[("disabled", C["disabled_bg"]), ("selected", C["accent"]),
                                          ("active", C["accent_soft"])],
               upperbordercolor=[("selected", C["accent"])], lowerbordercolor=[("selected", C["accent"])],
               foreground=[("disabled", C["faint"])], background=[("active", C["card"])])
    # The wheel over a combo or spin box changes its VALUE in ttk. Scrolling a form
    # with the pointer resting on "Organization" or "How many rows" then silently
    # changed a filter or a count (seen live, HISTORY.md Phase 114). Here the wheel
    # scrolls the page instead and never touches a value; arrows, typing and the
    # drop-down still change it on purpose.
    for cls in ("TCombobox", "TSpinbox"):
        root.bind_class(cls, "<MouseWheel>", _wheel_scrolls_the_page)
    row_h = max(S(28), int(tkfont.Font(root, font=F["body"]).metrics("linespace") * 1.6))
    st.configure("Table.Treeview", background=C["field"], fieldbackground=C["field"], foreground=C["text"],
                 rowheight=row_h, bordercolor=C["line"], lightcolor=C["line"], darkcolor=C["line"],
                 font=F["body"])
    st.map("Table.Treeview", background=[("selected", C["accent_soft"])],
           foreground=[("selected", C["text"])])
    st.configure("Table.Treeview.Heading", background=C["tile"], foreground=C["muted"],
                 font=F["label"], relief="flat", bordercolor=C["line"], lightcolor=C["tile"],
                 darkcolor=C["line"], padding=(S(8), S(6)))
    st.map("Table.Treeview.Heading", background=[("active", C["line"])])
    st.layout("Table.Treeview", [("Treeview.field", {"sticky": "nswe", "border": "1", "children": [
        ("Treeview.padding", {"sticky": "nswe", "children": [
            ("Treeview.treearea", {"sticky": "nswe"})]})]})])
    st.configure("Run.Horizontal.TProgressbar", troughcolor=C["line"], background=C["accent"],
                 bordercolor=C["line"], lightcolor=C["accent"], darkcolor=C["accent"], thickness=S(10))
    st.configure("Done.Horizontal.TProgressbar", troughcolor=C["line"], background=C["ok"],
                 bordercolor=C["line"], lightcolor=C["ok"], darkcolor=C["ok"], thickness=S(10))
    st.layout("Slim.Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {
        "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})], "sticky": "ns"})])
    st.layout("Console.Vertical.TScrollbar", st.layout("Slim.Vertical.TScrollbar"))
    # (name, trough, thumb, thumb under the pointer). clam paints a thumb that fills
    # the whole trough in its grey "disabled" colour, and draws grip lines, unless
    # both are overridden here.
    for name, trough, thumb, hover in (("Slim.Vertical.TScrollbar", C["bg"], C["thumb"], C["thumb_hover"]),
                                       ("Console.Vertical.TScrollbar", C["console"], C["console_thumb"],
                                        C["console_thumb_hover"])):
        st.configure(name, troughcolor=trough, background=thumb, bordercolor=trough,
                     lightcolor=thumb, darkcolor=thumb, gripcount=0, arrowsize=S(9))
        st.map(name, background=[("disabled", trough), ("pressed", hover), ("active", hover)],
               lightcolor=[("disabled", trough), ("pressed", hover), ("active", hover)],
               darkcolor=[("disabled", trough), ("pressed", hover), ("active", hover)],
               bordercolor=[("disabled", trough)])
    return st


# --------------------------------------------------------------------------
# Widgets
# --------------------------------------------------------------------------
class FlatButton(tk.Label):
    """A flat, coloured button with hover and a real disabled state."""

    KINDS = {}

    @classmethod
    def refresh_kinds(cls):
        """Re-read the colours of every kind from the current theme."""
        on = C["on_accent"]             # dark themes use a light accent with dark text on it
        cls.KINDS = {
            # kind: (background, hover, text, border)
            "primary": (C["accent"], C["accent_hover"], on, C["accent"]),
            "success": (C["ok"], C["ok_hover"], "#FFFFFF", C["ok"]),
            "danger": (C["err"], C["err_hover"], "#FFFFFF", C["err"]),
            "dark": (C["dark"], C["dark_hover"], "#FFFFFF", C["dark"]),
            "secondary": (C["raised"], C["raised_hover"], C["text"], C["border"]),
            "ghost": (C["card"], C["accent_soft"], C["accent"], C["card"]),
            "seg_on": (C["accent"], C["accent"], on, C["accent"]),
            "seg_off": (C["raised"], C["raised_hover"], C["muted"], C["border"]),
            "chip": (C["tile"], C["accent_soft"], C["accent"], C["border"]),
            "tab_on": (C["card"], C["card"], C["accent"], C["card"]),
            "tab_off": (C["card"], C["raised_hover"], C["muted"], C["card"]),
        }

    def __init__(self, parent, text, command=None, kind="primary", font=None,
                 padx=16, pady=7, width=None, anchor="center"):
        super().__init__(parent, text=text, font=font or F["button"], padx=S(padx), pady=S(pady),
                         bd=0, highlightthickness=1, takefocus=1, anchor=anchor,
                         **({"width": width} if width else {}))
        self.command = command
        self.enabled = True
        self._hover = False
        self.kind = kind
        self._paint()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonRelease-1>", self._on_click)
        self.bind("<Return>", self._on_click)
        self.bind("<space>", self._on_click)

    def _paint(self):
        bg, hover, fg, border = self.KINDS[self.kind]
        if not self.enabled:
            self.configure(bg=C["disabled_bg"], fg=C["disabled_fg"], cursor="arrow",
                           highlightbackground=C["disabled_bg"], highlightcolor=C["disabled_bg"])
            return
        self.configure(bg=hover if self._hover else bg, fg=fg, cursor="hand2",
                       highlightbackground=border, highlightcolor=C["accent"])

    def set_kind(self, kind):
        self.kind = kind
        self._paint()

    def set_enabled(self, flag):
        self.enabled = bool(flag)
        self._paint()

    def set_text(self, text):
        self.configure(text=text)

    def _on_enter(self, _e=None):
        self._hover = True
        self._paint()

    def _on_leave(self, _e=None):
        self._hover = False
        self._paint()

    def _on_click(self, _e=None):
        if self.enabled and self.command:
            self.command()
        return "break"


class Card(tk.Frame):
    """A white panel with a thin border and an optional numbered title."""

    def __init__(self, parent, title=None, step=None, subtitle=None, pad=16, right=None):
        super().__init__(parent, bg=C["card"], highlightthickness=1,
                         highlightbackground=C["border"], bd=0)
        if title:
            head = tk.Frame(self, bg=C["card"])
            head.pack(fill="x", padx=S(pad), pady=(S(pad - 2), 0))
            if step is not None:
                badge = tk.Canvas(head, width=S(24), height=S(24), bg=C["card"], highlightthickness=0)
                badge.create_oval(1, 1, S(23), S(23), fill=C["accent_soft"], outline="")
                badge.create_text(S(12), S(12), text=str(step), fill=C["accent"], font=F["badge"])
                badge.pack(side="left", padx=(0, S(10)))
            titles = tk.Frame(head, bg=C["card"])
            titles.pack(side="left", fill="x", expand=True)
            tk.Label(titles, text=title, font=F["card_title"], bg=C["card"], fg=C["text"],
                     anchor="w").pack(fill="x")
            if subtitle:
                tk.Label(titles, text=subtitle, font=F["small"], bg=C["card"], fg=C["muted"],
                         anchor="w", justify="left").pack(fill="x")
            self.head_right = tk.Frame(head, bg=C["card"])
            self.head_right.pack(side="right")
        self.body = tk.Frame(self, bg=C["card"])
        self.body.pack(fill="both", expand=True, padx=S(pad), pady=S(pad - 2))


class Segmented(tk.Frame):
    """Two to four mutually exclusive choices drawn as one joined control."""

    def __init__(self, parent, options, variable, command=None, font=None, padx=14):
        super().__init__(parent, bg=C["border"], bd=0)
        self.variable = variable
        self.command = command
        self.buttons = {}
        for i, (value, label) in enumerate(options):
            b = FlatButton(self, label, command=lambda v=value: self._choose(v), kind="seg_off",
                           font=font or F["button"], padx=padx, pady=5)
            b.configure(highlightthickness=0)
            b.grid(row=0, column=i, padx=(1 if i == 0 else 0, 1), pady=1, sticky="nsew")
            self.buttons[value] = b
        variable.trace_add("write", lambda *_a: self._refresh())
        self._refresh()

    def _choose(self, value):
        self.variable.set(value)
        if self.command:
            self.command()

    def _refresh(self):
        for value, b in self.buttons.items():
            b.set_kind("seg_on" if self.variable.get() == value else "seg_off")

    def set_enabled(self, flag):
        for b in self.buttons.values():
            b.set_enabled(flag)
        if flag:
            self._refresh()

    def set_labels(self, labels):
        for value, text in labels.items():
            if value in self.buttons:
                self.buttons[value].set_text(text)


class StatTile(tk.Frame):
    def __init__(self, parent, caption, value="-", color=None):
        super().__init__(parent, bg=C["tile"], highlightthickness=1, highlightbackground=C["line"])
        self.bar = tk.Frame(self, bg=color or C["border"], width=S(4))
        self.bar.pack(side="left", fill="y")
        inner = tk.Frame(self, bg=C["tile"])
        inner.pack(side="left", fill="both", expand=True, padx=S(12), pady=S(8))
        tk.Label(inner, text=caption.upper(), font=F["tiny"], bg=C["tile"], fg=C["muted"],
                 anchor="w").pack(fill="x")
        self.value = tk.Label(inner, text=value, font=F["stat"], bg=C["tile"], fg=C["text"], anchor="w")
        self.value.pack(fill="x")

    def set(self, value, fg=None):
        self.value.configure(text=value, fg=fg or C["text"])


class Pill(tk.Label):
    STYLES = {                         # style: (background token, text token) of the theme
        "idle": ("tile", "muted"), "busy": ("warn_soft", "warn_text"),
        "ready": ("accent_soft", "accent"), "run": ("ok_soft", "ok_text"),
        "stop": ("err_soft", "err_text"),
    }

    def __init__(self, parent):
        super().__init__(parent, font=F["badge"], padx=S(12), pady=S(4), bd=0, highlightthickness=1)
        self.set("idle", "Not connected")

    def set(self, style, text):
        bg, fg = (C[k] for k in self.STYLES[style])
        self.configure(text="●  " + text, bg=bg, fg=fg, highlightbackground=C["border"] if style == "idle" else bg)


def _wheel_scrolls_the_page(event):
    widget = event.widget
    while widget is not None and not isinstance(widget, ScrollFrame):
        widget = getattr(widget, "master", None)
    if widget is not None:
        widget.scroll(event.delta)
    return "break"


class ScrollFrame(tk.Frame):
    """A vertically scrolling column; the scroll bar appears only when needed."""

    def scroll(self, delta):
        first, last = self.canvas.yview()
        if not (first <= 0.0 and last >= 1.0):
            self.canvas.yview_scroll(int(-delta / 120) * 3, "units")

    def __init__(self, parent, bg):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                 style="Slim.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", lambda _e: self._update())
        self.canvas.bind("<Configure>", lambda e: (self.canvas.itemconfigure(self._win, width=e.width),
                                                  self._update()))
        # ONE application-wide wheel handler for every scroll column. Each column used
        # to add its own with bind_all, and those stayed bound to dead columns every
        # time the window was rebuilt for a new theme or text size.
        if ScrollFrame._wheel_root is not self._root():
            self.bind_all("<MouseWheel>", ScrollFrame._wheel, add="+")
            ScrollFrame._wheel_root = self._root()

    _wheel_root = None

    def _on_scroll(self, first, last):
        self.bar.set(first, last)
        needed = not (float(first) <= 0.0 and float(last) >= 1.0)
        if needed and not self.bar.winfo_ismapped():
            self.bar.pack(side="right", fill="y", padx=(S(2), 0))
        elif not needed and self.bar.winfo_ismapped():
            self.bar.pack_forget()

    def _update(self):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    @staticmethod
    def _wheel(event):
        if isinstance(event.widget, (tk.Text, ttk.Treeview)):
            return                          # they scroll themselves
        widget = event.widget
        while widget is not None and not isinstance(widget, ScrollFrame):
            widget = getattr(widget, "master", None)
        if widget is not None:
            try:
                widget.scroll(event.delta)
            except tk.TclError:
                pass


def field_label(parent, text, hint=None):
    box = tk.Frame(parent, bg=C["card"])
    tk.Label(box, text=text, font=F["label"], bg=C["card"], fg=C["text"], anchor="w").pack(side="left")
    if hint:
        tk.Label(box, text="  " + hint, font=F["small"], bg=C["card"], fg=C["faint"],
                 anchor="w").pack(side="left")
    return box


def fit_wrap(label, holder, margin=0, least=160):
    """Wrap `label`'s text at the width of `holder`, following it as the person drags a
    divider or resizes the window. A fixed wrap width left text cut off in a narrowed
    panel and a ragged half-empty column in a widened one. `holder` must be a frame
    whose width the layout sets (a card body, a page column) - never one sized by the
    label itself, which would shrink step by step."""
    entries = getattr(holder, "_fit_labels", None)
    if entries is None:
        # One binding per holder; labels that were destroyed (a detail panel rebuilt on
        # every selection) drop out instead of piling up bindings.
        holder._fit_labels = entries = []
        holder.bind("<Configure>", lambda e: _fit_all(holder, e.width), add="+")
    entries.append((label, margin, least))
    if holder.winfo_width() > 1:                 # already laid out: no Configure is coming
        _fit_all(holder, holder.winfo_width())
    return label


def _fit_all(holder, holder_width):
    alive = []
    for label, margin, least in holder._fit_labels:
        try:
            if not label.winfo_exists():
                continue
            width = max(S(least), holder_width - (margin() if callable(margin) else S(margin)))
            if abs(int(label.cget("wraplength")) - width) > 2:
                label.configure(wraplength=width)
            alive.append((label, margin, least))
        except tk.TclError:
            pass
    holder._fit_labels = alive


def note(parent, text, fg=None, bg=None, wrap=380, font=None, fit=False, margin=8):
    lbl = tk.Label(parent, text=text, font=font or F["small"], bg=bg or C["card"], fg=fg or C["muted"],
                   anchor="w", justify="left", wraplength=S(wrap))
    return fit_wrap(lbl, parent, margin) if fit else lbl


class Banner(tk.Frame):
    """A soft coloured message strip (info / ok / warn / err)."""

    TONES = {"info": ("accent_soft", "accent"), "ok": ("ok_soft", "ok_text"),
             "warn": ("warn_soft", "warn_text"), "err": ("err_soft", "err_text")}

    def __init__(self, parent, text="", tone="info", wrap=520, action=None, action_text=None):
        super().__init__(parent, bd=0)
        self.bar = tk.Frame(self, width=S(4))
        self.bar.pack(side="left", fill="y")
        self.label = tk.Label(self, font=F["small"], anchor="w", justify="left", wraplength=S(wrap),
                              padx=S(12), pady=S(8))
        self.label.pack(side="left", fill="both", expand=True)
        self.button = None
        if action:
            self.button = FlatButton(self, action_text or "Open", command=action, kind="ghost",
                                     font=F["label"], padx=10, pady=4)
            self.button.pack(side="right", padx=S(8))
        self.set(text, tone)
        # The text follows the width of whatever holds the banner (always a filled column).
        fit_wrap(self.label, parent, margin=lambda: S(36) + (
            self.button.winfo_reqwidth() + S(16) if self.button is not None else 0))

    def set(self, text, tone="info"):
        soft, strong = self.TONES[tone]
        bg, fg = C[soft], C[strong]
        self.configure(bg=bg)
        self.bar.configure(bg=fg)
        self.label.configure(text=text, bg=bg, fg=fg)
        if self.button is not None:
            FlatButton.KINDS["ghost_" + tone] = (bg, C["card"], fg, bg)
            self.button.set_kind("ghost_" + tone)


class Dialog(tk.Toplevel):
    """A small modal in the app's own style. `buttons` = [(text, kind, value)],
    the last one is the default (Enter); Escape returns the first one's value."""

    ICONS = {"info": ("i", "accent", "accent_soft"), "ok": ("✓", "ok", "ok_soft"),
             "warn": ("!", "warn", "warn_soft"), "err": ("✕", "err", "err_soft"),
             "ask": ("?", "accent", "accent_soft")}

    def __init__(self, parent, title, message, buttons=(("OK", "primary", True),), icon="info",
                 details=None):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.configure(bg=C["card"])
        self.resizable(False, False)
        self.transient(parent)
        self.value = buttons[0][2]
        body = tk.Frame(self, bg=C["card"])
        body.pack(fill="both", expand=True, padx=S(24), pady=(S(22), S(12)))
        glyph, strong, soft = self.ICONS.get(icon, self.ICONS["info"])
        c = tk.Canvas(body, width=S(40), height=S(40), bg=C["card"], highlightthickness=0)
        c.create_oval(1, 1, S(39), S(39), fill=C[soft], outline="")
        c.create_text(S(20), S(20), text=glyph, fill=C[strong], font=F["card_title"])
        c.grid(row=0, column=0, rowspan=3, sticky="n", padx=(0, S(16)))
        tk.Label(body, text=title, font=F["card_title"], bg=C["card"], fg=C["text"],
                 anchor="w").grid(row=0, column=1, sticky="w")
        tk.Label(body, text=message, font=F["body"], bg=C["card"], fg=C["muted"], anchor="w",
                 justify="left", wraplength=S(440)).grid(row=1, column=1, sticky="w", pady=(S(4), 0))
        if details:
            box = tk.Frame(body, bg=C["tile"], highlightthickness=1, highlightbackground=C["line"])
            box.grid(row=2, column=1, sticky="we", pady=(S(12), 0))
            for i, (k, v) in enumerate(details):
                tk.Label(box, text=k, font=F["small"], bg=C["tile"], fg=C["muted"], anchor="w").grid(
                    row=i, column=0, sticky="w", padx=(S(12), S(16)), pady=S(3))
                tk.Label(box, text=v, font=F["label"], bg=C["tile"], fg=C["text"], anchor="w",
                         justify="left", wraplength=S(300)).grid(row=i, column=1, sticky="w",
                                                                pady=S(3), padx=(0, S(12)))
        row = tk.Frame(self, bg=C["tile"], highlightthickness=0)
        row.pack(fill="x")
        tk.Frame(row, bg=C["line"], height=1).pack(fill="x", side="top")
        inner = tk.Frame(row, bg=C["tile"])
        inner.pack(side="right", padx=S(16), pady=S(12))
        last = None
        for text, kind, value in buttons:
            b = FlatButton(inner, text, command=lambda v=value: self._done(v), kind=kind)
            b.pack(side="left", padx=(S(8), 0))
            last = b
        self.bind("<Escape>", lambda _e: self._done(buttons[0][2]))
        self.bind("<Return>", lambda _e: self._done(buttons[-1][2]))
        self.protocol("WM_DELETE_WINDOW", lambda: self._done(buttons[0][2]))
        self.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"+{px + max(0, (pw - w) // 2)}+{py + max(0, (ph - h) // 3)}")
        self.deiconify()
        self.grab_set()
        (last or self).focus_set()
        self.wait_window(self)

    def _done(self, value):
        self.value = value
        self.destroy()


class Table(tk.Frame):
    """A styled Treeview with a slim scroll bar. `columns` = [(key, title, width, anchor)];
    the first column may stretch. Rows are tagged ok / warn / err / muted for colour."""

    def __init__(self, parent, columns, height=10, select="browse", stretch=None):
        super().__init__(parent, bg=C["card"], highlightthickness=1, highlightbackground=C["line"])
        self.keys = [c[0] for c in columns]
        self.tree = ttk.Treeview(self, columns=self.keys, show="headings", height=height,
                                 style="Table.Treeview", selectmode=select)
        for key, title, width, anchor in columns:
            self.tree.heading(key, text=title, anchor=anchor)
            self.tree.column(key, width=S(width), minwidth=S(40), anchor=anchor,
                             stretch=(key == (stretch or self.keys[0])))
        bar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview,
                            style="Slim.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        for tag, fg in (("ok", C["ok_text"]), ("warn", C["warn_text"]), ("err", C["err_text"]),
                        ("muted", C["faint"]), ("info", C["accent"])):
            self.tree.tag_configure(tag, foreground=fg)

    def fill(self, rows, iid_key=None):
        """rows: [(values_dict, tag)]; keeps the selection when the same ids come back."""
        keep = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for i, (values, tag) in enumerate(rows):
            iid = str(values.get(iid_key)) if iid_key else str(i)
            self.tree.insert("", "end", iid=iid, values=[values.get(k, "") for k in self.keys],
                             tags=(tag,) if tag else ())
        still = [i for i in keep if self.tree.exists(i)]
        if still:
            self.tree.selection_set(still)

    def selected(self):
        return list(self.tree.selection())

    def set_cell(self, iid, key, value, tag=None):
        if self.tree.exists(iid):
            self.tree.set(iid, key, value)
            if tag is not None:
                self.tree.item(iid, tags=(tag,))


class NavItem(tk.Frame):
    """One entry of the left navigation."""

    def __init__(self, parent, glyph, text, command, badge_var=None):
        super().__init__(parent, bg=C["header"], cursor="hand2")
        self.command = command
        self.active = False
        self.bar = tk.Frame(self, bg=C["header"], width=S(4))
        self.bar.pack(side="left", fill="y")
        self.glyph = tk.Label(self, text=glyph, font=F["glyph"], bg=C["header"],
                              fg=C["header_muted"], width=2)
        self.glyph.pack(side="left", padx=(S(14), S(8)), pady=S(10))
        self.label = tk.Label(self, text=text, font=F["tab"], bg=C["header"], fg=C["header_text"],
                              anchor="w")
        self.label.pack(side="left", fill="x", expand=True)
        self.badge = tk.Label(self, text="", font=F["tiny"], bg=C["header"], fg=C["nav_badge"])
        self.badge.pack(side="right", padx=S(12))
        for w in (self, self.glyph, self.label, self.badge):
            w.bind("<Button-1>", lambda _e: self.command())
            w.bind("<Enter>", lambda _e: self._paint(hover=True))
            w.bind("<Leave>", lambda _e: self._paint())
        self._paint()

    def set_active(self, flag):
        self.active = flag
        self._paint()

    def set_badge(self, text):
        self.badge.configure(text=text)

    def _paint(self, hover=False):
        bg = C["header2"] if self.active else (C["nav_hover"] if hover else C["header"])
        for w in (self, self.glyph, self.label, self.badge):
            w.configure(bg=bg)
        self.bar.configure(bg=C["nav_bar"] if self.active else bg)
        self.glyph.configure(fg="#FFFFFF" if self.active else C["header_muted"])
        self.label.configure(fg="#FFFFFF" if self.active else C["header_text"])


def page_title(parent, title, subtitle=""):
    box = tk.Frame(parent, bg=C["bg"])
    tk.Label(box, text=title, font=F["title"], bg=C["bg"], fg=C["text"],
             anchor="w").pack(fill="x")
    if subtitle:                         # wraps at the page's width instead of running off it
        fit_wrap(tk.Label(box, text=subtitle, font=F["small"], bg=C["bg"], fg=C["muted"], anchor="w",
                          justify="left", wraplength=S(900)), box).pack(fill="x", pady=(S(2), 0))
    return box


def ask(parent, title, message, yes="Continue", no="Cancel", kind="primary", icon="ask", details=None):
    return Dialog(parent, title, message, ((no, "secondary", False), (yes, kind, True)),
                  icon=icon, details=details).value


def tell(parent, title, message, icon="info"):
    Dialog(parent, title, message, (("OK", "primary", True),), icon=icon)


class Split(tk.PanedWindow):
    """Two panes with a gap the person drags to resize them. The share of the first
    pane is kept as a fraction, so the window can grow or shrink and the panes keep
    their proportion; `Split.store` (set by the app) remembers it per `name` between
    runs. `tail` instead places the gap that many pixels from the far end on first use."""

    store = None                        # (get(name) -> fraction or None, put(name, fraction))

    def __init__(self, parent, name, first=0.6, orient="horizontal", tail=None):
        horizontal = orient == "horizontal"
        super().__init__(parent, orient=orient, bg=C["bg"], bd=0, sashwidth=S(12), sashpad=0,
                         sashrelief="flat", showhandle=False, opaqueresize=True,
                         sashcursor="sb_h_double_arrow" if horizontal else "sb_v_double_arrow")
        self.name, self.horizontal, self.tail = name, horizontal, tail
        saved = Split.store[0](name) if Split.store else None
        self.default = first
        self.fraction = saved if isinstance(saved, (int, float)) and 0.05 < saved < 0.95 else first
        self.pinned_tail = None          # pixels: keep the gap this far from the end (folded console)
        self._dragged = False
        self.bind("<Configure>", lambda _e: self.after_idle(self.place_sash), add="+")
        self.bind("<B1-Motion>", lambda _e: setattr(self, "_dragged", True), add="+")
        self.bind("<ButtonRelease-1>", self._remember, add="+")
        self.bind("<Double-Button-1>", lambda _e: self.reset(), add="+")

    def _size(self):
        return self.winfo_width() if self.horizontal else self.winfo_height()

    def place_sash(self):
        try:
            total = self._size()
            if total < 50 or len(self.panes()) < 2:
                return
            if self.pinned_tail is not None:
                pos = total - self.pinned_tail
            elif self.fraction is None:
                pos = total - S(self.tail or 200)
            else:
                pos = int(total * self.fraction)
            self.sash_place(0, pos, 1) if self.horizontal else self.sash_place(0, 1, pos)
        except tk.TclError:
            pass

    def _remember(self, _e=None):
        if not self._dragged or self.pinned_tail is not None:
            return
        self._dragged = False
        try:
            x, y = self.sash_coord(0)
        except tk.TclError:
            return
        total = self._size()
        if total > 50:
            self.fraction = round((x if self.horizontal else y) / total, 4)
            if Split.store:
                Split.store[1](self.name, self.fraction)

    def reset(self):
        """Double-click on the gap: back to the original split."""
        if self.pinned_tail is not None:
            return
        self.fraction = self.default
        if Split.store:
            Split.store[1](self.name, None)
        self.place_sash()

    def add(self, child, minsize=120, **kw):
        super().add(child, minsize=S(minsize), **kw)


class ThemeSwatch(tk.Frame):
    """A small picture of a theme (side bar, a card, an accent button) to click on."""

    def __init__(self, parent, name, palette, selected, command):
        border = palette["accent"] if selected else C["border"]
        super().__init__(parent, bg=C["card"], highlightthickness=2 if selected else 1,
                         highlightbackground=border, cursor="hand2")
        pic = tk.Canvas(self, width=S(150), height=S(78), bg=palette["bg"], highlightthickness=0,
                        cursor="hand2")
        p = palette
        pic.create_rectangle(0, 0, S(34), S(78), fill=p["header"], outline="")
        pic.create_rectangle(S(6), S(14), S(28), S(20), fill=p["header2"], outline="")
        pic.create_rectangle(0, S(14), S(3), S(20), fill=p["nav_bar"], outline="")
        for i in range(3):
            pic.create_rectangle(S(8), S(28 + 9 * i), S(26), S(31 + 9 * i), fill=p["header_muted"], outline="")
        pic.create_rectangle(S(44), S(10), S(142), S(68), fill=p["card"], outline=p["border"])
        pic.create_rectangle(S(52), S(18), S(110), S(22), fill=p["text"], outline="")
        pic.create_rectangle(S(52), S(28), S(130), S(31), fill=p["muted"], outline="")
        pic.create_rectangle(S(52), S(48), S(92), S(60), fill=p["accent"], outline="")
        pic.create_rectangle(S(98), S(48), S(132), S(60), fill=p["ok_soft"], outline="")
        pic.pack(padx=S(6), pady=(S(6), 0))
        row = tk.Frame(self, bg=C["card"])
        row.pack(fill="x", padx=S(8), pady=(S(4), S(6)))
        tk.Label(row, text=("✓  " if selected else "") + name, font=F["label"], bg=C["card"],
                 fg=C["accent"] if selected else C["text"], anchor="w").pack(side="left")
        for w in (self, pic, row, *row.winfo_children()):
            w.bind("<Button-1>", lambda _e: command(name))


FlatButton.refresh_kinds()
