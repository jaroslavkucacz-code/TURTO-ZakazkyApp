#!/usr/bin/env python3
"""Headless regression test for unattended TURTO CRM updates."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile
import threading
import time
import types


def load_module(root: pathlib.Path):
    path = root / "price_lists_domain" / "platform" / "automatic_updates.py"
    spec = importlib.util.spec_from_file_location("turto_automatic_updates_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_until(predicate, timeout: float = 4.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for automatic update worker")


def main() -> None:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    automatic_updates = load_module(root)

    with tempfile.TemporaryDirectory(prefix="turto_auto_update_test_") as td:
        temp = pathlib.Path(td)
        (temp / "crm_updater.pyw").write_text("# test updater\n", encoding="utf-8")
        package = temp / "update.zip"
        package.write_bytes(b"PK-test-package")

        settings: dict[str, str] = {}
        messages: list[tuple[str, str]] = []
        launched: list[tuple[list[str], dict]] = []
        launch_event = threading.Event()

        class Variable:
            def __init__(self):
                self.value = ""

            def set(self, value):
                self.value = str(value)

        class MessageBox:
            @staticmethod
            def askyesno(*_args, **_kwargs):
                raise AssertionError("Automatic update must never ask for confirmation")

            @staticmethod
            def showinfo(title, text, **_kwargs):
                messages.append((str(title), str(text)))

            @staticmethod
            def showerror(title, text, **_kwargs):
                messages.append((str(title), str(text)))

        class FakeApp:
            def __init__(self):
                self.update_source = Variable()
                self.delayed: list[tuple[int, object]] = []
                self.closed = False
                self._turto_closing = False

            def after(self, delay, callback):
                # Tk's zero-delay worker hand-off and short close delay execute
                # immediately; the 900 ms startup check remains inspectable.
                if int(delay) < 500:
                    callback()
                    return "immediate"
                self.delayed.append((int(delay), callback))
                return f"after-{len(self.delayed)}"

            def winfo_exists(self):
                return True

            def title(self, _value):
                return None

            def configure(self, **_kwargs):
                return None

            def close_app(self):
                self.closed = True
                self._turto_closing = True

        M = types.SimpleNamespace()
        M.App = FakeApp
        M.ROOT = temp
        M.DATA_ROOT = temp / "data"
        M.APP_VERSION = "6.3.30"
        M.messagebox = MessageBox
        M.set_setting = lambda key, value: settings.__setitem__(str(key), str(value))
        M.get_setting = lambda key, default="": settings.get(str(key), default)
        M._version_tuple = lambda value: tuple(
            int(part) for part in str(value or "0").split(".") if part.isdigit()
        )
        M._download_update_package = lambda _manifest: package

        runtime = types.SimpleNamespace(_live_update_checks=lambda _app: "legacy-dialog")
        old_runtime = sys.modules.get("crm_runtime")
        sys.modules["crm_runtime"] = runtime

        old_popen = automatic_updates.subprocess.Popen
        old_manifest = automatic_updates._read_official_manifest
        try:
            automatic_updates.subprocess.Popen = lambda command, **kwargs: (
                launched.append((list(command), dict(kwargs))),
                launch_event.set(),
                types.SimpleNamespace(pid=12345),
            )[-1]
            automatic_updates._read_official_manifest = lambda: {
                "version": "6.3.31",
                "file": "ZakazkyApp_v6.3.31.zip",
                "sha256": "test",
                "_base": automatic_updates.OFFICIAL_UPDATE_ROOT + "/",
            }

            automatic_updates.install(M)
            assert runtime._live_update_checks(None) is None
            assert getattr(M.App, "_turto_automatic_updates_v6331", False)

            app = M.App()
            assert len(app.delayed) == 1 and app.delayed[0][0] == 900
            app.delayed.pop(0)[1]()
            assert launch_event.wait(4), "Updater was not launched"
            wait_until(lambda: app.closed)

            assert len(launched) == 1
            command, kwargs = launched[0]
            assert command[1].endswith("crm_updater.pyw")
            assert command[2] == str(package)
            assert command[3] == str(temp)
            assert settings["pending_update"] == "6.3.31"
            assert settings["update_source"] == automatic_updates.OFFICIAL_UPDATE_ROOT
            assert settings["company_auto_updates"] == "1"
            assert not any(title == "Aktualizace" for title, _text in messages)

            # A manual check on the current version reports status, but still
            # never presents an install/download confirmation.
            automatic_updates._read_official_manifest = lambda: {
                "version": "6.3.30",
                "file": "same.zip",
                "_base": automatic_updates.OFFICIAL_UPDATE_ROOT + "/",
            }
            current = M.App()
            current.check_for_updates(silent=False)
            wait_until(lambda: any("aktuální verzi 6.3.30" in text for _title, text in messages))
            assert len(launched) == 1

            source = (root / "price_lists_domain" / "platform" / "automatic_updates.py").read_text(
                encoding="utf-8"
            )
            assert "askyesno" not in source
            assert "TURTO-Automatic-Update" in source
            assert "automatic_updates.log" in source
            print("TURTO CRM unattended automatic update test: OK")
        finally:
            automatic_updates.subprocess.Popen = old_popen
            automatic_updates._read_official_manifest = old_manifest
            if old_runtime is None:
                sys.modules.pop("crm_runtime", None)
            else:
                sys.modules["crm_runtime"] = old_runtime


if __name__ == "__main__":
    main()
