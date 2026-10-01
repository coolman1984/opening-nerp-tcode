"""The base of every page of the window."""
import tkinter as tk

import ui_kit as ui
from ui_kit import C, S


class Page(tk.Frame):
    """A page. `app` gives: run_task, log, session, show, call_soon, open_path, pages."""
    key = ""
    title = ""
    subtitle = ""

    def __init__(self, app, parent):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        head = ui.page_title(self, self.title, self.subtitle)
        head.pack(fill="x", padx=S(24), pady=(S(18), S(10)))
        self.head = head
        self.body = tk.Frame(self, bg=C["bg"])
        self.body.pack(fill="both", expand=True, padx=S(24), pady=(0, S(14)))
        self.build(self.body)

    def build(self, body):
        pass

    def on_show(self, **kwargs):
        pass

    def on_busy(self, busy):
        pass

    def keep(self):
        """What the page shows that a rebuild (new theme or text size) should not lose."""
        return None

    def restore(self, state):
        pass
