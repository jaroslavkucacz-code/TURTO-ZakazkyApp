"""Visual and small UX cleanup for the stable TURTO CRM 8.x desktop line.

This layer is intentionally late and non-business: it keeps the proven historical
widgets and workflows, while removing misleading EXE-era controls and making a
few old hard-coded visual elements follow the active application theme.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
from typing import Any

POLICY_OWNER = "price_lists_domain.platform.ui_polish_801"
SUPPORTED_THEMES = ("Světlý", "Tmavý")


def _walk(widget: Any):
    yield widget
    try:
        for child in widget.winfo_children():
            yield from _walk(child)
    except Exception:
        return


def _exists(widget: Any) -> bool:
    try:
        return bool(widget is not None and widget.winfo_exists())
    except Exception:
        return False


def _widget_text(widget: Any) -> str:
    try:
        return str(widget.cget("text") or "").strip()
    except Exception:
        return ""


def _palette(widget: Any) -> dict[str, str]:
    try:
        root = widget._root()
        data = dict(getattr(root, "palette", {}) or {})
    except Exception:
        data = {}
    return {
        "bg": data.get("bg", "#f2f4f5"),
        "panel": data.get("panel", "#fafbfb"),
        "field": data.get("field", "#ffffff"),
        "fg": data.get("fg", "#1c2429"),
        "muted": data.get("muted", "#6c777f"),
        "head": data.get("head", "#e9edef"),
        "select": data.get("select", "#d6b64c"),
        "border": data.get("border", "#d4dade"),
        "card": data.get("card", "#ffffff"),
        "accent": data.get("accent", "#d79f00"),
    }


def _is_dark(color: str) -> bool:
    token = str(color or "").strip().lstrip("#")
    if len(token) != 6:
        return False
    try:
        r, g, b = (int(token[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return False
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) < 128


def _configure_muted_styles(app: Any) -> None:
    pal = _palette(app)
    style = ttk.Style(app)
    style.configure(
        "Muted.TLabel",
        background=pal["bg"],
        foreground=pal["muted"],
        font=("Calibri", 10),
    )
    style.configure(
        "PanelMuted.TLabel",
        background=pal["panel"],
        foreground=pal["muted"],
        font=("Calibri", 10),
    )
    style.configure(
        "CardMuted.TLabel",
        background=pal["card"],
        foreground=pal["muted"],
        font=("Calibri", 10),
    )


def _theme_aware_calendar(self) -> None:
    pal = _palette(self)
    dark = _is_dark(pal["bg"])
    bg = pal["bg"]
    panel = pal["panel"]
    card = pal["card"]
    fg = pal["fg"]
    muted = pal["muted"]
    head = pal["head"]
    select = pal["select"]
    border = pal["border"]
    accent = pal["accent"]
    selected_fg = "#ffffff" if dark else "#111111"

    pop = tk.Toplevel(self)
    pop.title("Vybrat datum")
    pop.transient(self.winfo_toplevel())
    pop.resizable(False, False)
    pop.configure(background=bg)
    pop.bind("<Escape>", lambda _event: pop.destroy())

    try:
        selected = datetime.strptime(self.variable.get().strip(), "%Y-%m-%d").date()
    except Exception:
        selected = None
    current = selected or date.today()
    state = {"year": current.year, "month": current.month}

    shell = tk.Frame(pop, bg=bg, bd=0, padx=10, pady=10)
    shell.pack(fill="both", expand=True)
    frame = tk.Frame(
        shell,
        bg=card,
        bd=0,
        highlightthickness=1,
        highlightbackground=border,
    )
    frame.pack(fill="both", expand=True)

    header = tk.Frame(frame, bg=head, padx=9, pady=8)
    header.pack(fill="x")
    button_common = {
        "font": ("Calibri", 14, "bold"),
        "fg": fg,
        "bg": head,
        "activeforeground": fg,
        "activebackground": select,
        "bd": 0,
        "relief": "flat",
        "highlightthickness": 0,
        "width": 2,
    }
    previous = tk.Button(header, text="‹", **button_common)
    previous.pack(side="left")
    title = tk.Label(
        header,
        text="",
        font=("Calibri", 12, "bold"),
        fg=fg,
        bg=head,
    )
    title.pack(side="left", expand=True)
    following = tk.Button(header, text="›", **button_common)
    following.pack(side="right")

    grid = tk.Frame(frame, bg=card, padx=8, pady=8)
    grid.pack(fill="both", expand=True)

    def choose(day: int) -> None:
        self.variable.set(f"{state['year']:04d}-{state['month']:02d}-{day:02d}")
        pop.destroy()

    def change(delta: int) -> None:
        month = state["month"] + delta
        year = state["year"]
        if month < 1:
            month = 12
            year -= 1
        if month > 12:
            month = 1
            year += 1
        state.update(year=year, month=month)
        render()

    previous.configure(command=lambda: change(-1))
    following.configure(command=lambda: change(1))

    def render() -> None:
        for widget in grid.winfo_children():
            widget.destroy()
        title.configure(
            text=f"{self.MONTHS[state['month'] - 1].capitalize()} {state['year']}"
        )
        for column, name in enumerate(self.DAYS):
            label_fg = accent if column >= 5 else muted
            tk.Label(
                grid,
                text=name,
                width=4,
                font=("Calibri", 9, "bold"),
                bg=card,
                fg=label_fg,
            ).grid(row=0, column=column, padx=2, pady=(0, 5))

        today = date.today()
        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(
            state["year"], state["month"]
        )
        for row, week in enumerate(weeks, 1):
            for column, day in enumerate(week):
                if not day:
                    tk.Label(grid, text="", width=4, bg=card).grid(
                        row=row, column=column, padx=2, pady=2
                    )
                    continue

                current_date = date(state["year"], state["month"], day)
                day_bg = card
                day_fg = accent if column >= 5 else fg
                relief = "flat"
                border_width = 0
                if selected and current_date == selected:
                    day_bg = select
                    day_fg = selected_fg
                    relief = "solid"
                    border_width = 1
                if current_date == today:
                    day_bg = accent
                    day_fg = "#111111"
                    relief = "solid"
                    border_width = 1

                button = tk.Button(
                    grid,
                    text=str(day),
                    width=3,
                    height=1,
                    font=("Calibri", 10),
                    bg=day_bg,
                    fg=day_fg,
                    activebackground=head,
                    activeforeground=fg,
                    relief=relief,
                    bd=border_width,
                    highlightthickness=0,
                    command=lambda value=day: choose(value),
                )
                button.grid(row=row, column=column, padx=2, pady=2, ipadx=2, ipady=2)

    render()

    footer = tk.Frame(frame, bg=panel, padx=9, pady=8)
    footer.pack(fill="x")
    tk.Button(
        footer,
        text="Vymazat datum",
        font=("Calibri", 9),
        bd=0,
        relief="flat",
        highlightthickness=0,
        bg=panel,
        fg=muted,
        activebackground=head,
        activeforeground=fg,
        command=lambda: (self.variable.set(""), pop.destroy()),
    ).pack(side="left")
    tk.Button(
        footer,
        text="Dnes",
        font=("Calibri", 9, "bold"),
        bd=0,
        relief="flat",
        highlightthickness=0,
        bg=accent,
        fg="#111111",
        activebackground=select,
        activeforeground="#111111" if not dark else "#ffffff",
        command=lambda: (self.variable.set(date.today().isoformat()), pop.destroy()),
    ).pack(side="right")

    # Open close to the field instead of at an arbitrary Windows position.
    try:
        pop.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 4
        pop.geometry(f"+{x}+{y}")
    except Exception:
        pass


def _polish_settings(app: Any, M: Any) -> None:
    try:
        page = app.tabs["settings"]
    except Exception:
        return

    # Three historical light-theme names currently resolve to the same palette.
    # Present only the two genuinely distinct choices and normalize old values.
    current = str(getattr(getattr(app, "theme", None), "get", lambda: "")() or "").strip()
    if current not in SUPPORTED_THEMES and hasattr(app, "theme"):
        app.theme.set("Světlý")

    theme_variable = str(getattr(app, "theme", ""))
    update_variable = str(getattr(app, "update_source", ""))
    update_button = None
    update_panel = None
    legacy_info = None

    for widget in _walk(page):
        try:
            widget_class = widget.winfo_class()
        except Exception:
            widget_class = ""
        text = _widget_text(widget)

        if widget_class == "TCombobox":
            try:
                if str(widget.cget("textvariable")) == theme_variable:
                    widget.configure(values=SUPPORTED_THEMES)
            except Exception:
                pass

        if not (getattr(sys, "frozen", False) and sys.platform.startswith("win")):
            continue

        if widget_class == "TEntry":
            try:
                if update_variable and str(widget.cget("textvariable")) == update_variable:
                    widget.grid_remove()
            except Exception:
                pass
        elif text == "Vybrat složku…":
            try:
                widget.grid_remove()
            except Exception:
                pass
        elif text.startswith("Výchozí kanál:"):
            legacy_info = widget
            try:
                widget.grid_remove()
            except Exception:
                pass
        elif text == "Zkontrolovat aktualizace":
            update_button = widget
            update_panel = getattr(widget, "master", None)

    if update_button is not None:
        try:
            update_button.grid_configure(
                row=12,
                column=0,
                columnspan=1,
                sticky="w",
                pady=(8, 4),
            )
        except Exception:
            pass

    if update_panel is not None:
        try:
            label = ttk.Label(
                update_panel,
                text=(
                    f"Produkční Windows kanál · TURTO CRM {getattr(M, 'APP_VERSION', '')} · "
                    "aktualizace se ověřují automaticky"
                ),
                style="PanelMuted.TLabel",
            )
            label.grid(
                row=12,
                column=1,
                columnspan=2,
                sticky="w",
                padx=(12, 0),
                pady=(8, 4),
            )
            app._turto_windows_channel_label = label
        except Exception:
            pass


def _polish_footer(app: Any, M: Any) -> None:
    footer = getattr(app, "footer_db", None)
    if not _exists(footer):
        return
    try:
        database = Path(getattr(M, "DB", "zakazky.db"))
        footer.configure(text=f"Databáze: {database.name or 'zakazky.db'}")
    except Exception:
        pass


def apply(M: Any) -> None:
    if getattr(M, "_turto_ui_polish_801", False):
        return
    M._turto_ui_polish_801 = True

    App = M.App

    old_apply_theme = App.apply_theme

    def apply_theme(self, theme=None, save=True):
        if theme is not None and str(theme).strip() not in SUPPORTED_THEMES:
            theme = "Světlý"
        result = old_apply_theme(self, theme, save)
        _configure_muted_styles(self)
        return result

    App.apply_theme = apply_theme

    old_build_settings = App.build_settings

    def build_settings(self, *args, **kwargs):
        result = old_build_settings(self, *args, **kwargs)
        _polish_settings(self, M)
        return result

    App.build_settings = build_settings

    old_build = App.build

    def build(self, *args, **kwargs):
        result = old_build(self, *args, **kwargs)
        _polish_footer(self, M)
        return result

    App.build = build

    # DatePicker is a reusable base widget, so one replacement fixes all action,
    # request, project and task dialogs without touching their business logic.
    M.DatePicker.open_calendar = _theme_aware_calendar

    M.UI_POLISH_OWNER = POLICY_OWNER
    M.UI_SUPPORTED_THEMES = SUPPORTED_THEMES


__all__ = ["apply", "POLICY_OWNER", "SUPPORTED_THEMES"]
