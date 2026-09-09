#!/usr/bin/env python3
"""Behavioral regression checks for the TURTO CRM 8.0 Windows updater."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_release(root: Path, version: str, marker: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "TURTO CRM.exe").write_bytes(("main-" + marker).encode())
    (root / "TURTO CRM Updater.exe").write_bytes(("updater-" + marker).encode())
    (root / "version.json").write_text(
        json.dumps({"version": version, "channel": "windows", "build": "test"}),
        encoding="utf-8",
    )
    internal = root / "_internal"
    internal.mkdir(parents=True, exist_ok=True)
    (internal / f"{marker}.txt").write_text(marker, encoding="utf-8")


def _zip_release(source: Path, package: Path) -> None:
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in source.rglob("*"):
            if path.is_file():
                archive.write(path, Path(source.name) / path.relative_to(source))


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    base = repo / "ZakazkyApp_base_6.1"
    build = repo / "build" / "windows"
    sys.path.insert(0, str(base))

    old_env = dict(os.environ)
    try:
        with tempfile.TemporaryDirectory(prefix="turto800_updater_") as td:
            root = Path(td)
            os.environ["USERPROFILE"] = str(root / "profile")
            os.environ["LOCALAPPDATA"] = str(root / "local")
            os.environ["TURTO_CRM_DATA_ROOT"] = str(root / "data-root")
            os.environ.pop("TURTO_CRM_DATABASE", None)

            updater = _load_module("turto_updater_800_test", build / "updater_800.pyw")
            exe_policy = _load_module(
                "turto_exe_distribution_800_test",
                base / "price_lists_domain" / "platform" / "exe_distribution.py",
            )

            # Dedicated Windows manifest contract must reject legacy/ambiguous data.
            valid_manifest = {
                "format": "turto-crm-windows-update-v1",
                "channel": "windows",
                "version": "8.0.1",
                "package": "TURTO_CRM_Update_8.0.1.zip",
                "sha256": "a" * 64,
            }
            normalized = exe_policy._validate_windows_manifest(valid_manifest)
            assert normalized["version"] == "8.0.1"
            for mutation in (
                {**valid_manifest, "format": "legacy"},
                {**valid_manifest, "channel": "legacy"},
                {**valid_manifest, "package": "ZakazkyApp_v8.0.1.zip"},
                {**valid_manifest, "package": "../TURTO_CRM_Update_8.0.1.zip"},
                {**valid_manifest, "sha256": "1234"},
            ):
                try:
                    exe_policy._validate_windows_manifest(mutation)
                except ValueError:
                    pass
                else:
                    raise AssertionError(f"Invalid Windows manifest accepted: {mutation}")

            installed = root / "installed"
            payload = root / "TURTO_CRM_8.0.1"
            _write_release(installed, "8.0.0", "old")
            _write_release(payload, "8.0.1", "new")
            # Real Inno installations contain these files. Payloads must not.
            (installed / "unins000.exe").write_bytes(b"inno-uninstaller")
            (installed / "unins000.dat").write_bytes(b"inno-metadata")

            assert updater._validate_release(installed, installed=True) == "8.0.0"
            try:
                updater._validate_release(installed)
            except RuntimeError as exc:
                assert "odinstala" in str(exc).casefold()
            else:
                raise AssertionError("Payload validator accepted Inno uninstaller metadata")
            assert updater._validate_release(payload, "8.0.1") == "8.0.1"

            package = root / "TURTO_CRM_Update_8.0.1.zip"
            _zip_release(payload, package)
            package_sha = hashlib.sha256(package.read_bytes()).hexdigest()
            assert updater._verify_package_hash(package, package_sha) == package_sha
            try:
                updater._verify_package_hash(package, "0" * 64)
            except ValueError as exc:
                assert "sha-256" in str(exc).casefold()
            else:
                raise AssertionError("Updater accepted an incorrect package SHA-256")

            # ZIP traversal must be rejected before anything can reach the install dir.
            malicious = root / "malicious.zip"
            with zipfile.ZipFile(malicious, "w") as archive:
                archive.writestr("../escape.txt", b"escape")
            with tempfile.TemporaryDirectory(prefix="turto800_extract_") as extract_dir:
                try:
                    updater._source_root(malicious, Path(extract_dir))
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("Updater accepted ZIP path traversal")
            assert not (root / "escape.txt").exists()

            # A successful transaction replaces only program-owned files and keeps
            # the Inno uninstaller metadata untouched.
            snapshot_path, snapshot_sha = updater._replace_program_with_rollback(
                payload,
                installed,
                current_version="8.0.0",
                expected_version="8.0.1",
            )
            assert snapshot_path.is_file()
            assert hashlib.sha256(snapshot_path.read_bytes()).hexdigest() == snapshot_sha
            assert updater._validate_release(installed, "8.0.1", installed=True) == "8.0.1"
            assert (installed / "_internal" / "new.txt").is_file()
            assert not (installed / "_internal" / "old.txt").exists()
            assert (installed / "unins000.exe").read_bytes() == b"inno-uninstaller"
            assert (installed / "unins000.dat").read_bytes() == b"inno-metadata"

            # Reset to an old installation and simulate a copy failure after the
            # updater already cleaned program-owned files. The second copy call is
            # snapshot restoration and must recover the original release.
            for path in list(installed.iterdir()):
                if path.name.casefold().startswith("unins"):
                    continue
                if path.is_dir():
                    import shutil
                    shutil.rmtree(path)
                else:
                    path.unlink()
            _write_release(installed, "8.0.0", "old")

            original_copy = updater._copy_release
            calls = {"count": 0}

            def fail_first_copy(source, target):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise OSError("simulated copy failure")
                return original_copy(source, target)

            updater._copy_release = fail_first_copy
            try:
                updater._replace_program_with_rollback(
                    payload,
                    installed,
                    current_version="8.0.0",
                    expected_version="8.0.1",
                )
            except RuntimeError as exc:
                text = str(exc).casefold()
                assert "automaticky obnovena" in text and "simulated copy failure" in text
            else:
                raise AssertionError("Simulated update failure did not fail the transaction")
            finally:
                updater._copy_release = original_copy

            assert updater._validate_release(installed, "8.0.0", installed=True) == "8.0.0"
            assert (installed / "_internal" / "old.txt").is_file()
            assert not (installed / "_internal" / "new.txt").exists()
            assert (installed / "unins000.exe").read_bytes() == b"inno-uninstaller"
            assert (installed / "unins000.dat").read_bytes() == b"inno-metadata"

            # Downloader must hash the byte stream itself and remember the official
            # expected values for the independently re-hashing updater process.
            download_bytes = package.read_bytes()

            class FakeResponse:
                def __init__(self, payload_bytes: bytes):
                    self._stream = io.BytesIO(payload_bytes)

                def read(self, size=-1):
                    return self._stream.read(size)

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            class FakeUpdates:
                OFFICIAL_UPDATE_ROOT = "https://updates.example.invalid"

            class FakeModule:
                DATA_ROOT = root / "download-data"

            manifest = {
                **valid_manifest,
                "sha256": package_sha,
                "_base": FakeUpdates.OFFICIAL_UPDATE_ROOT + "/",
            }
            original_urlopen = exe_policy.urllib.request.urlopen
            exe_policy.urllib.request.urlopen = lambda request, timeout=0: FakeResponse(download_bytes)
            try:
                downloaded = exe_policy._download_windows_package(FakeModule, FakeUpdates, manifest)
            finally:
                exe_policy.urllib.request.urlopen = original_urlopen
            assert downloaded.read_bytes() == download_bytes
            assert FakeModule._turto_windows_expected_update_sha256 == package_sha
            assert FakeModule._turto_windows_expected_update_version == "8.0.1"

    finally:
        os.environ.clear()
        os.environ.update(old_env)

    print("TURTO CRM 8.0 Windows updater transaction: OK")


if __name__ == "__main__":
    main()
