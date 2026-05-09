"""Light/Dark UI theme for the tkinter GUI.

Dark palette is intentionally near-black (#000000 / #0a0a0a) so it works
well at night without any blue-grey haze. ttk widgets use the `clam`
backend so background/foreground configuration actually takes effect.
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from .config import SETTINGS_DIR, UI_PREFS_FILE


# True-black dark palette
DARK = {
    "bg":          "#000000",
    "bg_alt":      "#0a0a0a",
    "panel":       "#111111",
    "panel_hi":    "#1a1a1a",
    "fg":          "#e8e8e8",
    "fg_muted":    "#9a9a9a",
    "accent":      "#3a8dde",
    "border":      "#2a2a2a",
    "select_bg":   "#264f78",
    "input_bg":    "#0e0e0e",
    "log_info":    "#cfcfcf",
    "log_warn":    "#e0a040",
    "log_error":   "#ff5a5a",
}

# Light palette (close to system default but consistent across OS)
LIGHT = {
    "bg":          "#f4f4f4",
    "bg_alt":      "#ffffff",
    "panel":       "#ececec",
    "panel_hi":    "#dcdcdc",
    "fg":          "#1a1a1a",
    "fg_muted":    "#5a5a5a",
    "accent":      "#1f6feb",
    "border":      "#bdbdbd",
    "select_bg":   "#cfe1ff",
    "input_bg":    "#ffffff",
    "log_info":    "#222222",
    "log_warn":    "#aa6600",
    "log_error":   "#cc0000",
}


def palette(dark: bool) -> dict[str, str]:
    return DARK if dark else LIGHT


def apply_theme(root: tk.Misc, dark: bool) -> None:
    """Apply the theme to root + all current children, ttk + classic tk."""
    p = palette(dark)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    bg, fg = p["bg"], p["fg"]
    panel = p["panel"]
    input_bg = p["input_bg"]
    border = p["border"]
    select_bg = p["select_bg"]
    muted = p["fg_muted"]

    root.configure(bg=bg)

    # Base
    style.configure(".",
                    background=bg, foreground=fg,
                    fieldbackground=input_bg, bordercolor=border,
                    troughcolor=panel, focuscolor=p["accent"])
    # Frames & labels
    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, foreground=fg)
    style.configure("TLabelframe", background=bg, foreground=fg,
                    bordercolor=border, lightcolor=border, darkcolor=border)
    style.configure("TLabelframe.Label", background=bg, foreground=fg)

    # Buttons
    style.configure("TButton",
                    background=panel, foreground=fg,
                    bordercolor=border, lightcolor=border, darkcolor=border,
                    focusthickness=0, padding=(8, 4))
    style.map("TButton",
              background=[("active", p["panel_hi"]),
                          ("disabled", p["bg_alt"])],
              foreground=[("disabled", muted)])

    # Inputs
    style.configure("TEntry", fieldbackground=input_bg, foreground=fg,
                    insertcolor=fg, bordercolor=border)
    style.map("TEntry",
              fieldbackground=[("disabled", p["bg_alt"])],
              foreground=[("disabled", muted)])
    style.configure("TCombobox", fieldbackground=input_bg, foreground=fg,
                    background=panel, bordercolor=border, arrowcolor=fg)
    style.map("TCombobox",
              fieldbackground=[("readonly", input_bg)],
              foreground=[("disabled", muted)])
    style.configure("TSpinbox", fieldbackground=input_bg, foreground=fg,
                    background=panel, bordercolor=border, arrowcolor=fg,
                    insertcolor=fg)

    # Toggles
    style.configure("TCheckbutton", background=bg, foreground=fg,
                    indicatorcolor=input_bg, focusthickness=0)
    style.map("TCheckbutton",
              background=[("active", bg)],
              indicatorcolor=[("selected", p["accent"])])
    style.configure("TRadiobutton", background=bg, foreground=fg,
                    indicatorcolor=input_bg, focusthickness=0)
    style.map("TRadiobutton",
              background=[("active", bg)],
              indicatorcolor=[("selected", p["accent"])])

    # Progress
    style.configure("Horizontal.TProgressbar",
                    background=p["accent"], troughcolor=panel,
                    bordercolor=border, lightcolor=p["accent"],
                    darkcolor=p["accent"])

    # Scrollbar
    style.configure("Vertical.TScrollbar",
                    background=panel, troughcolor=bg,
                    bordercolor=border, arrowcolor=fg)
    style.configure("Horizontal.TScrollbar",
                    background=panel, troughcolor=bg,
                    bordercolor=border, arrowcolor=fg)

    _apply_classic(root, p)


def _apply_classic(parent: tk.Misc, p: dict[str, str]) -> None:
    """Recursively apply colors to non-ttk widgets (Text, Listbox, Frame)."""
    for w in parent.winfo_children():
        cls = w.winfo_class()
        try:
            if cls == "Text":
                w.configure(
                    bg=p["input_bg"], fg=p["fg"],
                    insertbackground=p["fg"],
                    selectbackground=p["select_bg"],
                    selectforeground=p["fg"],
                    highlightthickness=0, borderwidth=0,
                )
                # Re-apply log tag colors if they exist
                try:
                    w.tag_configure("info", foreground=p["log_info"])
                    w.tag_configure("warn", foreground=p["log_warn"])
                    w.tag_configure("error", foreground=p["log_error"])
                except tk.TclError:
                    pass
            elif cls == "Listbox":
                w.configure(
                    bg=p["input_bg"], fg=p["fg"],
                    selectbackground=p["select_bg"],
                    selectforeground=p["fg"],
                    highlightthickness=0,
                )
            elif cls in ("Frame", "Toplevel", "Tk"):
                w.configure(bg=p["bg"])
            elif cls == "Label":
                w.configure(bg=p["bg"], fg=p["fg"])
            elif cls == "Menu":
                w.configure(bg=p["panel"], fg=p["fg"],
                            activebackground=p["panel_hi"],
                            activeforeground=p["fg"])
        except tk.TclError:
            pass
        _apply_classic(w, p)


# --- preference persistence ---------------------------------------------
def load_prefs() -> dict:
    try:
        return json.loads(UI_PREFS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:  # noqa: BLE001
        return {}


def save_prefs(prefs: dict) -> None:
    try:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        UI_PREFS_FILE.write_text(
            json.dumps(prefs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass
