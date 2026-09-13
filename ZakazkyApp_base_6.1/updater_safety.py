"""Non-destructive Windows updater primitives. No security-product exceptions."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

UPDATER_EXE = "TURTO CRM Updater.exe"
RUNTIME_DIR = "_updater_runtime"


class UpdateBlocked(RuntimeError):
    """Stop without modifying the installed application."""


def is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def plain_files(root: Path):
    """Do not follow Windows junctions or Unix symlinks, including the root."""
    if is_link(root):
        raise UpdateBlocked(f"Odkaz nebo junction není povolen: {root}")
    for child in sorted(root.iterdir()):
        if is_link(child):
            raise UpdateBlocked(f"Odkaz nebo junction není povolen: {child}")
        if child.is_dir():
            yield from plain_files(child)
        elif child.is_file():
            yield child
        else:
            raise UpdateBlocked(f"Nepodporovaný typ souboru: {child}")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class FileLock:
    """OS-owned, non-blocking lock, automatically released when a process exits."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and is_link(self.path):
            raise UpdateBlocked("Zámek aktualizátoru nesmí být odkaz.")
        stream = self.path.open("a+b")
        try:
            if stream.seek(0, 2) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise UpdateBlocked("Jiná aktualizace již běží. CRM zůstává beze změny.") from exc
        self.stream = stream
        return self

    def __exit__(self, *args):
        if self.stream is not None:
            try:
                self.stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            finally:
                self.stream.close()
                self.stream = None


def stage_lock(stage: Path) -> Path:
    return stage.parent / (stage.name + ".lock")


def bundle_files(executable: Path) -> dict[str, Path]:
    executable = Path(executable)
    if not executable.is_file() or is_link(executable):
        raise UpdateBlocked("Chybí původní aktualizátor nebo nejde o běžný soubor.")
    runtime = executable.parent / RUNTIME_DIR
    if not runtime.is_dir():
        raise UpdateBlocked("Chybí runtime aktualizátoru. Použijte úplný oficiální instalátor.")
    files = {UPDATER_EXE: executable}
    files.update({p.relative_to(executable.parent).as_posix(): p for p in plain_files(runtime)})
    if not any(name.lower().endswith(".dll") for name in files):
        raise UpdateBlocked("Runtime aktualizátoru neobsahuje potřebné knihovny.")
    return files


def prepare_stage(executable: Path, stage: Path, copy_file=shutil.copy2) -> tuple[Path, Path]:
    """Reuse unchanged runtime. Never recreate a missing/quarantined same build."""
    with FileLock(stage_lock(stage)):
        files = bundle_files(executable)
        hashes = {name: digest(path) for name, path in files.items()}
        fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
        if stage.exists() and is_link(stage):
            raise UpdateBlocked("Pracovní složka aktualizátoru nesmí být odkaz.")
        stage.mkdir(parents=True, exist_ok=True)
        receipt = stage / "receipt.json"
        runtime = stage / "runtime"
        previous = None
        if receipt.exists():
            try:
                if is_link(receipt):
                    raise ValueError("linked receipt")
                previous = json.loads(receipt.read_text(encoding="utf-8"))
            except Exception as exc:
                raise UpdateBlocked("Poškozený záznam aktualizátoru; automatické obnovení bylo zastaveno.") from exc
        if previous and previous.get("fingerprint") == fingerprint:
            if not previous.get("complete"):
                raise UpdateBlocked("Příprava tohoto aktualizátoru již selhala. Soubor nebude znovu vytvářen.")
            try:
                actual = {p.relative_to(runtime).as_posix(): digest(p) for p in plain_files(runtime)}
            except Exception as exc:
                raise UpdateBlocked("Pracovní aktualizátor chybí nebo je zablokovaný. Nebude automaticky obnoven.") from exc
            if actual != hashes:
                raise UpdateBlocked("Pracovní aktualizátor byl odstraněn nebo změněn. Nebude automaticky obnoven.")
            return runtime, runtime / UPDATER_EXE

        # Persist the attempt BEFORE creating executable files. A failed copy is
        # not retried on every automatic check. Only a different official build
        # can replace the receipt. Never touch antivirus quarantine or policy.
        write_json(receipt, {"fingerprint": fingerprint, "complete": False})
        if runtime.exists():
            list(plain_files(runtime))
            shutil.rmtree(runtime)
        runtime.mkdir()
        try:
            for name, source in files.items():
                target = runtime / name
                target.parent.mkdir(parents=True, exist_ok=True)
                copy_file(source, target)
            actual = {p.relative_to(runtime).as_posix(): digest(p) for p in plain_files(runtime)}
            if actual != hashes:
                raise UpdateBlocked("Pracovní aktualizátor neodpovídá originálu.")
            write_json(receipt, {"fingerprint": fingerprint, "complete": True})
        except Exception as exc:
            raise UpdateBlocked("Aktualizátor nelze bezpečně připravit. CRM zůstává otevřené; pokus se nebude opakovat.") from exc
        return runtime, runtime / UPDATER_EXE


def _kernel():
    from ctypes import wintypes as wt
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k.OpenProcess.restype = wt.HANDLE
    k.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    k.WaitForSingleObject.restype = wt.DWORD
    k.CloseHandle.argtypes = [wt.HANDLE]
    k.CloseHandle.restype = wt.BOOL
    return k


def wait_for_process(pid: int, timeout: float = 120.0) -> None:
    """Wait without termination rights. Timeout/access denial always aborts."""
    if pid == 0:
        return
    if pid < 0 or pid == os.getpid() or timeout < 0:
        raise UpdateBlocked("Neplatný proces nebo limit čekání aktualizace.")
    if os.name == "nt":
        k = _kernel()
        handle = k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # process already exited / ERROR_INVALID_PARAMETER
                return
            raise UpdateBlocked(f"Nelze bezpečně ověřit ukončení CRM (Windows {error}).")
        try:
            result = k.WaitForSingleObject(handle, min(int(timeout * 1000), 0xFFFFFFFE))
            if result == 0:
                return
            if result != 258:
                raise UpdateBlocked(f"Kontrola ukončení CRM selhala (Windows {ctypes.get_last_error()}).")
        finally:
            k.CloseHandle(handle)
    else:
        deadline = time.monotonic() + timeout
        while True:
            try:
                os.kill(pid, 0)  # POSIX-only: never executed on Windows
            except ProcessLookupError:
                return
            except PermissionError as exc:
                raise UpdateBlocked("Nelze bezpečně ověřit ukončení CRM.") from exc
            if time.monotonic() >= deadline:
                break
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    raise UpdateBlocked("CRM se včas neukončilo. Aktualizace byla zastavena; instalace zůstala nedotčená.")


def preflight_files(root: Path) -> None:
    files = list(plain_files(root))
    if os.name != "nt":
        return
    from ctypes import wintypes as wt
    k = _kernel()
    k.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE]
    k.CreateFileW.restype = wt.HANDLE
    invalid = ctypes.c_void_p(-1).value
    for path in files:
        # Exclusive read/write/delete access detects running images and open
        # DLLs without truncating, deleting or modifying a single byte.
        handle = k.CreateFileW(str(path), 0xC0010000, 0, None, 3, 0x80, None)
        if handle == invalid:
            error = ctypes.get_last_error()
            raise UpdateBlocked(f"Soubor je používán nebo je přístup blokován: {path.name} (Windows {error}). Instalace zůstává nedotčená.")
        k.CloseHandle(handle)


def rename_directory(source: Path, target: Path) -> None:
    source.rename(target)


def replace_directory(source: Path, target: Path, *, copy_release, validate, owned: set[str], expected_version: str) -> None:
    """Prepare completely, then rename. Keep old directory on recovery failure.

    Two filesystem renames are not one atomic operation across a power loss.
    A durable journal and original directory are retained across that gap.
    No installed file is unlinked during preparation or the switch.
    """
    target = target.resolve()
    preflight_files(target)
    work = Path(tempfile.mkdtemp(prefix="." + target.name + ".update-", dir=target.parent))
    staged, previous = work / "new", work / "previous"
    journal = work / "transaction.json"
    success = restored = False
    try:
        # Preserve installer metadata and other non-program-owned local files.
        shutil.copytree(target, staged)
        for name in owned:
            path = staged / name
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        copy_release(source, staged)
        validate(staged, expected_version, installed=True)
        write_json(journal, {"target": str(target), "phase": "prepared", "version": expected_version})
        preflight_files(target)
        rename_directory(target, previous)
        rename_directory(staged, target)
        validate(target, expected_version, installed=True)
        write_json(journal, {"target": str(target), "phase": "committed", "version": expected_version})
        success = True
    except BaseException as exc:
        if previous.exists():
            try:
                if target.exists():
                    rename_directory(target, work / "failed-new")
                rename_directory(previous, target)
                restored = True
            except BaseException as recovery:
                raise RuntimeError(f"Obnova instalace se nezdařila. Původní program je zachován v {previous}. Chyba: {exc}; obnova: {recovery}") from exc
            raise RuntimeError(f"Aktualizace selhala; původní verze byla automaticky obnovena. Důvod: {exc}") from exc
        restored = target.exists()
        raise RuntimeError(f"Aktualizace selhala před výměnou; původní verze zůstala nedotčená. Důvod: {exc}") from exc
    finally:
        if success or restored:
            shutil.rmtree(work, ignore_errors=True)


def recover_interrupted(target: Path) -> None:
    """Recover a recorded interrupted rename, never guess among old versions."""
    if target.exists():
        return
    candidates = []
    for work in target.parent.glob("." + target.name + ".update-*"):
        if not work.is_dir() or is_link(work):
            continue
        try:
            record = json.loads((work / "transaction.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if record.get("target") == str(target.resolve()) and (work / "previous").is_dir():
            candidates.append(work / "previous")
    if len(candidates) == 1:
        list(plain_files(candidates[0]))
        rename_directory(candidates[0], target)
    elif candidates:
        raise UpdateBlocked("Existuje více přerušených instalací. Použijte úplný oficiální instalátor; zálohy nebyly změněny.")
