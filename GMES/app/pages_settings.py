"""Appearance: theme, text font, console font, text size and the dividers.

Every choice is applied at once (the window is rebuilt with it) and kept in
data/settings.json, so the next start looks the same.
"""
import tkinter as tk

import app_settings
import ui_kit as ui
from page_base import Page
from ui_kit import C, F, S

SAMPLE = "Detail Inspection  ·  Q321KUM00  ·  2026-09-30  ·  1,234 rows"
MONO_SAMPLE = "10:15:37  Record check PASSED - 10 of 10"


class AppearancePage(Page):
    key = "appearance"
    title = "Appearance"
    subtitle = ("Theme, fonts and text size for this window - applied at once and remembered. "
                "Drag the gap between any two panels to resize them; double-click a gap to put it back.")

    def build(self, body):
        self.fonts, self.monos = ui.installed_fonts(self)
        split = ui.Split(body, "appearance", first=0.5)
        split.pack(fill="both", expand=True)
        left = ui.ScrollFrame(split, C["bg"])
        split.add(left, minsize=420)
        right = ui.ScrollFrame(split, C["bg"])
        split.add(right, minsize=380)
        self._build_theme(left.inner)
        self._build_size(left.inner)
        self._build_layout(left.inner)
        self._build_fonts(right.inner)

    # ---- theme ----------------------------------------------------------------
    def _build_theme(self, col):
        card = ui.Card(col, "Theme", subtitle="Colours of the whole window")
        card.pack(fill="x", pady=(0, S(12)), padx=(0, S(6)))
        grid = tk.Frame(card.body, bg=C["card"])
        grid.pack(fill="x")
        for i, (name, palette) in enumerate(ui.THEMES.items()):
            sw = ui.ThemeSwatch(grid, name, palette, name == ui.APPEARANCE["theme"],
                                lambda n: self.choose(theme=n))
            sw.grid(row=i // 3, column=i % 3, padx=(0, S(10)), pady=(0, S(10)), sticky="w")

    # ---- size -----------------------------------------------------------------
    def _build_size(self, col):
        card = ui.Card(col, "Text size", subtitle="Every text in the window, tables and the console too")
        card.pack(fill="x", pady=(0, S(12)), padx=(0, S(6)))
        self.v_size = tk.StringVar(value=str(ui.APPEARANCE["size"]))
        ui.Segmented(card.body, [(str(s), f"{s} %") for s in ui.TEXT_SIZES], self.v_size,
                     command=lambda: self.choose(size=int(self.v_size.get())), padx=12).pack(anchor="w")
        ui.note(card.body, "100 % is the normal size. Larger sizes suit a big screen across a room "
                           "or tired eyes; the side bar grows with them.", wrap=520).pack(
            fill="x", pady=(S(8), 0))

    # ---- layout ---------------------------------------------------------------
    def _build_layout(self, col):
        card = ui.Card(col, "Layout", subtitle="Panels you resized are remembered per page")
        card.pack(fill="x", pady=(0, S(12)), padx=(0, S(6)))
        row = tk.Frame(card.body, bg=C["card"])
        row.pack(fill="x")
        ui.FlatButton(row, "Reset every divider", command=self.reset_layout, kind="secondary",
                      font=F["label"], padx=12, pady=6).pack(side="left")
        ui.FlatButton(row, "Back to the original look", command=self.reset_all, kind="ghost",
                      font=F["label"], padx=12, pady=6).pack(side="left", padx=(S(8), 0))
        ui.note(card.body, "The Activity console at the bottom can also be dragged taller or shorter, "
                           "or hidden with its Hide button.", wrap=520).pack(fill="x", pady=(S(10), 0))

    # ---- fonts ----------------------------------------------------------------
    def _build_fonts(self, col):
        card = ui.Card(col, "Text font", subtitle="Fonts found on this PC")
        card.pack(fill="x", pady=(0, S(12)), padx=(S(6), S(4)))
        for name in self.fonts or ["TkDefaultFont"]:
            self._font_row(card.body, name, (name, F["body"][1] + 1), SAMPLE, "font")
        card = ui.Card(col, "Console font", subtitle="The Activity console and other fixed-width text")
        card.pack(fill="x", pady=(0, S(12)), padx=(S(6), S(4)))
        for name in self.monos or ["TkFixedFont"]:
            self._font_row(card.body, name, (name, F["mono"][1] + 1), MONO_SAMPLE, "mono")

    def _font_row(self, parent, name, font, sample, which):
        selected = ui.APPEARANCE[which] == name
        bg = C["accent_soft"] if selected else C["tile"]
        row = tk.Frame(parent, bg=bg, highlightthickness=1,
                       highlightbackground=C["accent"] if selected else C["line"], cursor="hand2")
        row.pack(fill="x", pady=(0, S(6)))
        head = tk.Frame(row, bg=bg)
        head.pack(fill="x", padx=S(12), pady=(S(7), 0))
        tk.Label(head, text=name, font=F["label"], bg=bg, fg=C["accent"] if selected else C["muted"],
                 anchor="w").pack(side="left")
        if selected:
            tk.Label(head, text="✓ in use", font=F["tiny"], bg=bg, fg=C["accent"]).pack(side="right")
        tk.Label(row, text=sample, font=font, bg=bg, fg=C["text"], anchor="w").pack(
            fill="x", padx=S(12), pady=(S(2), S(8)))
        widgets = [row, head, *head.winfo_children(), *row.winfo_children()]
        for w in widgets:
            w.bind("<Button-1>", lambda _e: self.choose(**{which: name}))

    # ---- actions --------------------------------------------------------------
    def choose(self, **change):
        if all(ui.APPEARANCE.get(k) == v for k, v in change.items()):
            return
        if self.app.apply_appearance(**change):
            self.app.log("Appearance: " + ", ".join(f"{k} {v}" for k, v in change.items()), "ok")

    def reset_layout(self):
        app_settings.save(panes={}, activity_folded=False)
        if self.app.apply_appearance():
            self.app.log("Every divider is back where it started.", "ok")

    def reset_all(self):
        app_settings.save(panes={}, activity_folded=False)
        if self.app.apply_appearance(**ui.APPEARANCE_DEFAULTS):
            self.app.log("Appearance: back to the original look.", "ok")
