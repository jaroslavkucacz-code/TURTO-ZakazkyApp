"""Exercise the copied runtime with no installed PostgreSQL/Python in PATH."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
exe = ROOT / 'dist/TURTO-CRM-Sitovy-Pilot/TURTO-CRM-Mistni-Ukazka.exe'
output = ROOT / 'artifacts/network/windows'
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='turto-local-ci-') as temporary:
    work = Path(temporary)
    config = work / 'company-settings'
    config.mkdir()
    sentinel = config / 'connection.json'
    sentinel.write_bytes(b'Existing company settings must stay unchanged.\n')
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith('PG')}
    env.update(LOCALAPPDATA=str(work / 'local-user'), TURTO_PILOT_CONFIG_ROOT=str(config),
               TURTO_TEST_LOCAL_DEMO='1', PGHOST='192.0.2.1', PGHOSTADDR='192.0.2.1',
               PATH=str(Path(os.environ['SystemRoot']) / 'System32'))
    report = output / 'local-demo.json'
    result = subprocess.run([str(exe), '--demo-smoke-test', '--report', str(report)],
                            cwd=work, env=env, timeout=240)
    data = json.loads(report.read_text(encoding='utf-8'))
    assert result.returncode == 0 and data['ok'] and data['frozen'], data
    assert sentinel.read_bytes() == b'Existing company settings must stay unchanged.\n'
    print('Frozen local demo: create, edit, conflict, reader, history, graceful cleanup OK')
    crash_report = work / 'crash-ready.json'
    process = subprocess.Popen([str(exe), '--demo-smoke-test', '--wait-for-termination',
                                '--report', str(crash_report)], cwd=work, env=env)
    handle = None
    try:
        deadline = time.monotonic() + 150
        while not crash_report.exists():
            assert process.poll() is None, 'Crash cleanup fixture exited before ready'
            if time.monotonic() >= deadline: raise TimeoutError('Crash fixture not ready')
            time.sleep(0.1)
        ready = json.loads(crash_report.read_text(encoding='utf-8'))
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, ready['pid'])  # SYNCHRONIZE, read-only process handle
        assert handle
        process.kill(); process.wait(timeout=10)
        assert kernel.WaitForSingleObject(handle, 10000) == 0, 'PostgreSQL survived demo process termination'
        # Job termination is asynchronous. The postmaster can exit just before
        # a worker releases its inherited listening socket. Await the whole
        # endpoint closing, with a hard deadline, rather than racing one probe.
        closed_deadline = time.monotonic() + 10
        while True:
            with socket.socket() as probe:
                probe.settimeout(2)
                if probe.connect_ex(('127.0.0.1', ready['port'])) != 0:
                    break
            if time.monotonic() >= closed_deadline:
                raise AssertionError('Demo endpoint stayed open after OS job termination')
            time.sleep(0.1)
        data.update(forced_stop=True, company_settings_unchanged=True)
        report.write_text(json.dumps(data, indent=2), encoding='utf-8')
        print('Forced termination: PostgreSQL stopped automatically; company settings untouched')
    finally:
        if process.poll() is None: process.kill(); process.wait(timeout=10)
        if handle: kernel.CloseHandle(handle)
