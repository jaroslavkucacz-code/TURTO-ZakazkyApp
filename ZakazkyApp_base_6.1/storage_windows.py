"""Exclusive Windows handles for an obsolete SQLite backup and all sidecars.

CreateFileW share mode zero rejects existing users and prevents new opens.
Handles stay open through copy verification and deletion marking. Nothing is
removed merely by acquiring a handle. No SQLite connection changes old backups.
"""
from contextlib import ExitStack
import ctypes
import hashlib
import os
from pathlib import Path


class LockedBackup:
    def __init__(self, paths):
        self.paths = list(paths)  # main database first
        self.stack = ExitStack()
        self.streams = {}

    def __enter__(self):
        if os.name != "nt":
            raise RuntimeError("Úklid záloh s doprovodnými soubory vyžaduje Windows.")
        import msvcrt
        from ctypes import wintypes as w
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
        self.kernel.CreateFileW.restype = w.HANDLE
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.CloseHandle.restype = w.BOOL
        self.kernel.SetFileInformationByHandle.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD]
        self.kernel.SetFileInformationByHandle.restype = w.BOOL
        try:
            for path in self.paths:
                # GENERIC_READ | DELETE, no sharing, OPEN_EXISTING. Never truncate.
                h = self.kernel.CreateFileW(str(path), 0x80010000, 0, None, 3, 0x80, None)
                if h == ctypes.c_void_p(-1).value:
                    raise OSError(f"Záloha je používána nebo je přístup blokován: {path.name} (Windows {ctypes.get_last_error()}).")
                try:
                    fd = msvcrt.open_osfhandle(h, os.O_RDONLY | os.O_BINARY)
                except Exception:
                    self.kernel.CloseHandle(h)
                    raise
                try:
                    stream = os.fdopen(fd, "rb")
                except Exception:
                    os.close(fd)
                    raise
                self.streams[path] = self.stack.enter_context(stream)
            return self
        except Exception:
            self.stack.close()
            raise

    def digest(self, path):
        stream = self.streams[path]
        stream.seek(0)
        result = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
        stream.seek(0)
        return result.hexdigest()

    def mark_delete(self, path):
        import msvcrt
        # FILE_DISPOSITION_INFO uses a one-byte BOOLEAN. Deletion occurs on close.
        flag = ctypes.c_ubyte(1)
        h = msvcrt.get_osfhandle(self.streams[path].fileno())
        if not self.kernel.SetFileInformationByHandle(h, 4, ctypes.byref(flag), ctypes.sizeof(flag)):
            raise OSError(f"Nelze odstranit {Path(path).name} (Windows {ctypes.get_last_error()}).")

    def __exit__(self, *args):
        # Sidecar handles close first, database last. Once the main file is
        # marked, no other process can reopen its name during partial cleanup.
        self.stack.close()
