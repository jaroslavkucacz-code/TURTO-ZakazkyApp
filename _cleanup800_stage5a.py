from pathlib import Path

ROOT = Path("ZakazkyApp_base_6.1")


def replace(path: str, old: str, new: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected block not found: {path}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def ensure_lifecycle_helper(path: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    marker = "from __future__ import annotations\n"
    if "import app_lifecycle\n" not in text:
        if marker not in text:
            raise SystemExit(f"future import marker not found: {path}")
        text = text.replace(marker, marker + "\nimport app_lifecycle\n", 1)
    text = text.replace("M.register_app_init_hook(", "app_lifecycle.register(M, ")
    p.write_text(text, encoding="utf-8")


replace(
    "v740_offer_defaults.py",
    '''    previous_app_init = M.App.__init__

    def app_init(self, *args, **kwargs):
        result = previous_app_init(self, *args, **kwargs)

        def tidy():
            try:
                mivo = getattr(self, "tabs", {}).get("mivo")
                offers = getattr(self, "tabs", {}).get("offers")
                if mivo is not None:
                    remove_columns_buttons(mivo)
                if offers is not None:
                    remove_columns_buttons(offers)
                button = getattr(
                    self, "_v710_mivo_columns_button", None
                )
                if _widget_exists(button):
                    button.destroy()
                self._v710_mivo_columns_button = None
                install_offer_context(self)
            except Exception:
                pass

        for delay in (0, 80, 260, 760, 1650):
            try:
                self.after(delay, tidy)
            except Exception:
                pass
        return result

    M.App.__init__ = app_init''',
    '''    def after_app_init(self, _result, _args, _kwargs):
        def tidy():
            try:
                mivo = getattr(self, "tabs", {}).get("mivo")
                offers = getattr(self, "tabs", {}).get("offers")
                if mivo is not None:
                    remove_columns_buttons(mivo)
                if offers is not None:
                    remove_columns_buttons(offers)
                button = getattr(
                    self, "_v710_mivo_columns_button", None
                )
                if _widget_exists(button):
                    button.destroy()
                self._v710_mivo_columns_button = None
                install_offer_context(self)
            except Exception:
                pass

        for delay in (0, 80, 260, 760, 1650):
            try:
                self.after(delay, tidy)
            except Exception:
                pass

    M.register_app_init_hook("v740.offer_toolbar_tidy", after=after_app_init)''',
)

replace(
    "v750_context_filters_offer_format.py",
    '''    previous_app_init = M.App.__init__

    def app_init(self: Any, *args: Any, **kwargs: Any):
        result = previous_app_init(self, *args, **kwargs)
        for delay in (0, 80, 260, 760, 1650):
            try:
                self.after(delay, lambda current=self: configure_workspaces(current))
            except Exception:
                pass
        return result

    M.App.__init__ = app_init''',
    '''    def after_app_init(self: Any, _result: Any, _args: tuple[Any, ...], _kwargs: dict[str, Any]) -> None:
        for delay in (0, 80, 260, 760, 1650):
            try:
                self.after(delay, lambda current=self: configure_workspaces(current))
            except Exception:
                pass

    M.register_app_init_hook("v750.configure_workspaces", after=after_app_init)''',
)

replace(
    "price_lists_domain/issued_offers/professional_workflow.py",
    '''    previous_init = M.App.__init__

    def app_init(self: Any, *args: Any, **kwargs: Any):
        result = previous_init(self, *args, **kwargs)
        try:
            self.bind(
                "<F1>",
                lambda _event: (
                    _open_help_topic(M, self, "help_start"),
                    "break",
                )[1],
                add="+",
            )
        except Exception:
            pass
        return result

    M.App.__init__ = app_init''',
    '''    def after_app_init(self: Any, _result: Any, _args: tuple[Any, ...], _kwargs: dict[str, Any]) -> None:
        try:
            self.bind(
                "<F1>",
                lambda _event: (
                    _open_help_topic(M, self, "help_start"),
                    "break",
                )[1],
                add="+",
            )
        except Exception:
            pass

    M.register_app_init_hook("v780.help_shortcut", after=after_app_init)''',
)

replace(
    "v770_runtime_policy.py",
    '''    previous_init = M.App.__init__
    def app_init(self, *args, **kwargs):
        result = previous_init(self, *args, **kwargs)
        _configure_identity(M, self)
        try:
            self.title("TURTO CRM")
        except Exception:
            pass
        self.after_idle(lambda current=self: _apply_branding(M, current))
        self.after_idle(lambda current=self: _install_action_layout(current))
        self.after(250, lambda current=self: _install_action_layout(current))
        _schedule_plexus_backfill(M, self)
        return result
    M.App.__init__ = app_init''',
    '''    def after_app_init(self, _result, _args, _kwargs):
        _configure_identity(M, self)
        try:
            self.title("TURTO CRM")
        except Exception:
            pass
        self.after_idle(lambda current=self: _apply_branding(M, current))
        self.after_idle(lambda current=self: _install_action_layout(current))
        self.after(250, lambda current=self: _install_action_layout(current))
        _schedule_plexus_backfill(M, self)
    M.register_app_init_hook("v770.final_runtime_policy", after=after_app_init)''',
)

for lifecycle_path in (
    "v740_offer_defaults.py",
    "v750_context_filters_offer_format.py",
    "price_lists_domain/issued_offers/professional_workflow.py",
    "v770_runtime_policy.py",
):
    ensure_lifecycle_helper(lifecycle_path)

p = Path("scripts/validate-800-app-lifecycle.py")
text = p.read_text(encoding="utf-8")
old = '''        "v631_diskdrop.py",\n    )'''
new = '''        "v631_diskdrop.py",\n        "v740_offer_defaults.py",\n        "v750_context_filters_offer_format.py",\n        "price_lists_domain/issued_offers/professional_workflow.py",\n        "v770_runtime_policy.py",\n    )'''
if old not in text:
    raise SystemExit("lifecycle migrated tuple marker not found")
text = text.replace(old, new, 1)
text = text.replace(
    '        assert "register_app_init_hook(" in text, filename\n',
    '        assert ("register_app_init_hook(" in text or "app_lifecycle.register(" in text), filename\n',
)
p.write_text(text, encoding="utf-8")

p = Path("scripts/audit-runtime-overrides.py")
text = p.read_text(encoding="utf-8")
marker = "CRITICAL_OWNER_BUDGETS = {\n"
if marker not in text:
    raise SystemExit("owner budget marker not found")
if '    "M.App.__init__": 3,\n' not in text:
    text = text.replace(marker, marker + '    "M.App.__init__": 3,\n', 1)
p.write_text(text, encoding="utf-8")

print("OK: prepared independently testable late App lifecycle migration")
