from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "ZakazkyApp_base_6.1"
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from price_lists_domain.platform import exe_distribution as dist


class FakeMessagebox:
    def __init__(self):
        self.errors = []

    def showerror(self, title, message, **kwargs):
        self.errors.append((str(title), str(message)))


class FakeModule:
    def __init__(self, root: Path, data_root: Path):
        self.ROOT = root
        self.DATA_ROOT = data_root
        self.APP_VERSION = "8.0.6"
        self._turto_windows_expected_update_version = "8.0.7"
        self._turto_windows_expected_update_sha256 = "a" * 64
        self.messagebox = FakeMessagebox()
        self.settings = {}

    def set_setting(self, key, value):
        self.settings[str(key)] = str(value)


class FakeUpdates:
    OFFICIAL_UPDATE_ROOT = "https://example.invalid/turto"

    def __init__(self):
        self.events = []

    def _log(self, module, event, detail=""):
        self.events.append((str(event), str(detail)))


class FakeApp:
    def __init__(self):
        self.closed = 0
        self.titles = []
        self.cursors = []
        self._turto_update_launching = False
        self._turto_update_security_warning_shown = False

    def after(self, delay, callback):
        # The staging contract is deterministic; execute callbacks immediately
        # so the test does not sleep for the production 800 ms health delay.
        callback()
        return f"after-{delay}"

    def close_app(self):
        self.closed += 1

    def title(self, value):
        self.titles.append(str(value))

    def configure(self, **kwargs):
        if "cursor" in kwargs:
            self.cursors.append(str(kwargs["cursor"]))


class FakeProcess:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def main() -> None:
    original_gettempdir = dist.tempfile.gettempdir
    original_popen = dist.subprocess.Popen
    original_local = os.environ.get("LOCALAPPDATA")

    with tempfile.TemporaryDirectory(prefix="turto-807-test-") as raw:
        sandbox = Path(raw)
        temp_root = sandbox / "temp"
        local_root = sandbox / "local"
        temp_root.mkdir()
        local_root.mkdir()
        os.environ["LOCALAPPDATA"] = str(local_root)
        dist.tempfile.gettempdir = lambda: str(temp_root)

        try:
            # 8.0.0-8.0.6 random TEMP copies: old copies are removed, a recent
            # directory is preserved to avoid disturbing a concurrently running updater.
            now = time.time()
            old = temp_root / "turto_crm_updater_old123"
            recent = temp_root / "turto_crm_updater_recent456"
            old.mkdir(); recent.mkdir()
            _write(old / dist.UPDATER_EXE, b"old")
            _write(recent / dist.UPDATER_EXE, b"recent")
            old_time = now - dist._LEGACY_STALE_SECONDS - 30
            recent_time = now - 5
            os.utime(old, (old_time, old_time))
            os.utime(recent, (recent_time, recent_time))

            removed = dist._cleanup_stale_legacy_updaters(now=now)
            assert not old.exists(), "stale legacy updater directory was not removed"
            assert recent.exists(), "recent updater directory must not be removed"
            assert any("old123" in value for value in removed)

            install_root = sandbox / "installed"
            data_root = sandbox / "data"
            installed_updater = install_root / dist.UPDATER_EXE
            package = data_root / "updates" / "downloads" / "TURTO_CRM_Update_8.0.7.zip"
            _write(installed_updater, (b"TURTO-UPDATER-807\n" * 4096))
            _write(package, b"verified-update-package")

            # Staging is deterministic and contains an exact byte-for-byte copy.
            stage1, staged1 = dist._prepare_updater_stage(installed_updater)
            assert stage1 == local_root / "TURTO CRM" / dist._UPDATER_STAGE_DIR
            assert staged1.read_bytes() == installed_updater.read_bytes()
            stage2, staged2 = dist._prepare_updater_stage(installed_updater)
            assert stage2 == stage1
            assert staged2 == staged1
            assert len(list((local_root / "TURTO CRM").glob("UpdaterRuntime"))) == 1

            # Successful updater survives the health probe -> CRM closes once.
            module = FakeModule(install_root, data_root)
            updates = FakeUpdates()
            app = FakeApp()
            dist.subprocess.Popen = lambda *args, **kwargs: FakeProcess(None)
            assert dist._launch_frozen_updater(module, updates, app, "8.0.7", package) is True
            assert app.closed == 1
            assert app._turto_update_launching is True
            assert any(event == "install-start-exe" for event, _ in updates.events)

            # New CRM startup can remove the one stable leftover staging copy.
            assert dist._cleanup_stage_copy() is True
            assert not dist._updater_stage_root().exists()

            # AV/process termination during the probe -> CRM stays open and warning is shown.
            module = FakeModule(install_root, data_root)
            updates = FakeUpdates()
            app = FakeApp()
            dist.subprocess.Popen = lambda *args, **kwargs: FakeProcess(5)
            assert dist._launch_frozen_updater(module, updates, app, "8.0.7", package) is True
            assert app.closed == 0
            assert app._turto_update_launching is False
            assert len(module.messagebox.errors) == 1
            assert any(event == "install-blocked-exe" for event, _ in updates.events)
            assert not dist._updater_stage_root().exists()

            # Popen failure (including executable removed/quarantined before start)
            # must not close CRM or create another random temp directory.
            module = FakeModule(install_root, data_root)
            updates = FakeUpdates()
            app = FakeApp()

            def blocked_popen(*args, **kwargs):
                raise FileNotFoundError("simulated endpoint-security quarantine")

            dist.subprocess.Popen = blocked_popen
            try:
                dist._launch_frozen_updater(module, updates, app, "8.0.7", package)
            except dist.UpdaterLaunchBlockedError:
                pass
            else:
                raise AssertionError("blocked updater launch did not fail closed")
            assert app.closed == 0
            assert app._turto_update_launching is False
            assert not dist._updater_stage_root().exists()

            # Only the deliberately recent legacy directory remains in TEMP.
            legacy_dirs = [
                p for p in temp_root.iterdir()
                if p.is_dir() and p.name.startswith(dist._LEGACY_TEMP_PREFIX)
            ]
            assert legacy_dirs == [recent], legacy_dirs

            source = (BASE / "price_lists_domain" / "platform" / "exe_distribution.py").read_text(encoding="utf-8")
            assert 'mkdtemp(prefix="turto_crm_updater_' not in source
            assert "_UPDATER_HEALTH_DELAY_MS = 800" in source

            print("Updater staging/AV safety validation OK")
        finally:
            dist.tempfile.gettempdir = original_gettempdir
            dist.subprocess.Popen = original_popen
            if original_local is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = original_local


if __name__ == "__main__":
    main()
