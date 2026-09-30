"""Look and feel of Samir Export: colours, fonts, and the few widgets tkinter lacks
(flat buttons, cards, a segmented control, stat tiles, a scrolling column, dialogs).

Standard library only - the .exe must run on a locked-down PC with nothing installed.
"""
import ctypes
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

C = {
    "bg": "#EEF2F7", "card": "#FFFFFF", "border": "#DCE3EC", "line": "#E8EDF3",
    "text": "#0F172A", "muted": "#5B6B82", "faint": "#94A3B8",
    "header": "#0B1B3F", "header2": "#16306B", "header_text": "#E6ECF7", "header_muted": "#9FB0D0",
    "accent": "#2563EB", "accent_hover": "#1D4ED8", "accent_soft": "#E8F0FE",
    "ok": "#15803D", "ok_hover": "#166534", "ok_soft": "#DCFCE7", "ok_text": "#166534",
    "warn": "#B45309", "warn_soft": "#FEF3C7", "warn_text": "#92400E",
    "err": "#DC2626", "err_hover": "#B91C1C", "err_soft": "#FEE2E2", "err_text": "#991B1B",
    "dark": "#7F1D1D", "dark_hover": "#5F1515",
    "disabled_bg": "#E6EBF2", "disabled_fg": "#A3AFC0",
    "tile": "#F7F9FC",
    "console": "#0B1220", "console_text": "#CBD5E1",
}

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


def setup_theme(root):
    """Fonts, ttk styles and the DPI scale. Call once, right after Tk()."""
    global SCALE
    SCALE = max(1.0, root.winfo_fpixels("1i") / 96.0)
    family = "Segoe UI" if "Segoe UI" in tkfont.families(root) else "TkDefaultFont"
    semi = "Segoe UI Semibold" if "Segoe UI Semibold" in tkfont.families(root) else family
    F.update({
        "body": (family, 10), "small": (family, 9), "tiny": (family, 8),
        "label": (semi, 9), "button": (semi, 10), "button_lg": (semi, 11),
        "card_title": (semi, 11), "title": (semi, 16), "subtitle": (family, 9),
        "tab": (semi, 10), "stat": (semi, 19), "status": (semi, 13),
        "mono": ("Consolas", 9), "badge": (semi, 9),
    })
    root.option_add("*Font", F["body"])
    root.option_add("*TCombobox*Listbox.font", F["body"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", "white")

    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure(".", font=F["body"], background=C["card"], foreground=C["text"],
                 bordercolor=C["border"], focuscolor=C["accent"])
    field = dict(fieldbackground="white", background="white", foreground=C["text"],
                 bordercolor=C["border"], lightcolor=C["border"], darkcolor=C["border"],
                 insertcolor=C["text"], padding=(S(8), S(5)), arrowcolor=C["muted"],
                 selectbackground=C["accent_soft"], selectforeground=C["text"])
    focus = [("focus", C["accent"])]
    for name in ("TEntry", "TCombobox", "TSpinbox"):
        st.configure(name, **field)
        st.map(name, bordercolor=focus, lightcolor=focus, darkcolor=focus,
               fieldbackground=[("readonly", "white"), ("disabled", C["tile"])],
               foreground=[("disabled", C["faint"])],
               selectbackground=[("readonly", "white")], selectforeground=[("readonly", C["text"])])
    st.configure("TSpinbox", arrowsize=S(11))
    st.configure("TCombobox", arrowsize=S(13))
    for name in ("TCheckbutton", "TRadiobutton"):
        st.configure(name, background=C["card"], foreground=C["text"], padding=(0, S(3)),
                     indicatorbackground="white", indicatorforeground="white",
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
    for name, trough, thumb, hover in (("Slim.Vertical.TScrollbar", C["bg"], "#C5CFDC", "#A7B4C6"),
                                       ("Console.Vertical.TScrollbar", C["console"], "#2A3549", "#3A4A66")):
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

    KINDS = {
        # kind: (background, hover, text, border)
        "primary": (C["accent"], C["accent_hover"], "white", C["accent"]),
        "success": (C["ok"], C["ok_hover"], "white", C["ok"]),
        "danger": (C["err"], C["err_hover"], "white", C["err"]),
        "dark": (C["dark"], C["dark_hover"], "white", C["dark"]),
        "secondary": ("white", "#F1F5F9", C["text"], C["border"]),
        "ghost": (C["card"], C["accent_soft"], C["accent"], C["card"]),
        "seg_on": (C["accent"], C["accent"], "white", C["accent"]),
        "seg_off": ("white", "#F1F5F9", C["muted"], C["border"]),
        "chip": (C["tile"], C["accent_soft"], C["accent"], C["border"]),
        "tab_on": (C["card"], C["card"], C["accent"], C["card"]),
        "tab_off": (C["card"], "#F4F7FB", C["muted"], C["card"]),
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
    STYLES = {
        "idle": ("#24386B", "#C9D5EE"), "busy": ("#6B4E16", "#FCD58A"),
        "ready": ("#1E4E9C", "#DCE8FF"), "run": ("#14532D", "#BBF7D0"),
        "stop": ("#6B1D1D", "#FECACA"),
    }

    def __init__(self, parent):
        super().__init__(parent, font=F["badge"], padx=S(12), pady=S(4), bd=0)
        self.set("idle", "Not connected")

    def set(self, style, text):
        bg, fg = self.STYLES[style]
        self.configure(text="●  " + text, bg=bg, fg=fg)


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
        self.bind_all("<MouseWheel>", self._wheel, add="+")

    def _on_scroll(self, first, last):
        self.bar.set(first, last)
        needed = not (float(first) <= 0.0 and float(last) >= 1.0)
        if needed and not self.bar.winfo_ismapped():
            self.bar.pack(side="right", fill="y", padx=(S(2), 0))
        elif not needed and self.bar.winfo_ismapped():
            self.bar.pack_forget()

    def _update(self):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _wheel(self, event):
        widget = event.widget
        while widget is not None:
            if widget is self:
                break
            widget = getattr(widget, "master", None)
        else:
            return
        if isinstance(event.widget, tk.Text):
            return
        self.scroll(event.delta)


def field_label(parent, text, hint=None):
    box = tk.Frame(parent, bg=C["card"])
    tk.Label(box, text=text, font=F["label"], bg=C["card"], fg=C["text"], anchor="w").pack(side="left")
    if hint:
        tk.Label(box, text="  " + hint, font=F["small"], bg=C["card"], fg=C["faint"],
                 anchor="w").pack(side="left")
    return box


def note(parent, text, fg=None, bg=None, wrap=380, font=None):
    return tk.Label(parent, text=text, font=font or F["small"], bg=bg or C["card"], fg=fg or C["muted"],
                    anchor="w", justify="left", wraplength=S(wrap))


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


def ask(parent, title, message, yes="Continue", no="Cancel", kind="primary", icon="ask", details=None):
    return Dialog(parent, title, message, ((no, "secondary", False), (yes, kind, True)),
                  icon=icon, details=details).value


def tell(parent, title, message, icon="info"):
    Dialog(parent, title, message, (("OK", "primary", True),), icon=icon)
