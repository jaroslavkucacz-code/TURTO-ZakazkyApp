"""Bounded JSON pipe between Tk's UI thread and the embedded Windows host."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading


def host_paths():
    if getattr(sys, 'frozen', False):
        folder = Path(sys._MEIPASS) / 'map-host'
    else:
        folder = Path(__file__).resolve().parents[3] / 'build' / 'windows' / '_generated' / 'map-host'
    return folder / 'TURTO Map.exe', folder / 'assets'


class Bridge:
    def __init__(self, frame, callback):
        self.frame, self.callback = frame, callback
        self.events = queue.Queue()
        self.outbox = queue.Queue(maxsize=20)
        self.closed = False
        self.process = None
        self.after = None
        exe, assets = host_paths()
        if sys.platform != 'win32' or not exe.is_file() or not (assets / 'index.html').is_file():
            raise RuntimeError('Vestavěná mapa je dostupná v úplné Windows instalaci TURTO CRM.')
        frame.update_idletasks()
        allowed = {'systemroot','windir','temp','tmp','localappdata','appdata','userprofile',
                   'path','programfiles','programfiles(x86)','programdata','commonprogramfiles'}
        env = {key:value for key,value in os.environ.items() if key.casefold() in allowed}
        # The helper never receives database paths, credentials or app objects.
        self.process = subprocess.Popen([str(exe), str(frame.winfo_id()), str(assets)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW, env=env)
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._write, daemon=True).start()
        frame.bind('<Destroy>', lambda event: self.close() if event.widget is frame else None, add='+')
        self._poll()

    def _read(self):
        try:
            for line in self.process.stdout:
                if len(line) <= 1_000_000:
                    try:
                        value = json.loads(line)
                        if isinstance(value, dict): self.events.put(value)
                    except ValueError:
                        pass
        finally:
            if not self.closed:
                self.events.put({'type':'error','message':'Mapové okno se zavřelo. Znovu otevřete CRM; případně doinstalujte WebView2 Runtime.'})

    def _write(self):
        while not self.closed:
            value = self.outbox.get()
            if value is None: break
            try:
                self.process.stdin.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')
                self.process.stdin.flush()
            except (OSError, ValueError):
                break

    def _poll(self):
        if self.closed: return
        for _ in range(30):
            try: value = self.events.get_nowait()
            except queue.Empty: break
            self.callback(value)
        if not self.closed:
            self.after = self.frame.after(80, self._poll)

    def send(self, value):
        if self.closed: return
        try: self.outbox.put_nowait(value)
        except queue.Full:
            self.callback({'type':'error','message':'Mapa nestíhá načíst změny. Počkejte a obnovte zobrazení.'})

    def close(self):
        if self.closed: return
        self.closed = True
        if self.after:
            try: self.frame.after_cancel(self.after)
            except Exception: pass
        try: self.outbox.put_nowait(None)
        except queue.Full: pass
        if self.process and self.process.poll() is None:
            self.process.terminate()
        if self.process:
            try: self.process.wait(timeout=2)
            except subprocess.TimeoutExpired: self.process.kill()
