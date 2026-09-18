"""Disposable, loopback-only PostgreSQL for the explicit Windows demonstration.

Never reads company profiles or production data. Each invocation owns a new
cluster; it cannot start, reuse, reconfigure or stop any installed database.
"""
from contextlib import contextmanager
import csv
import ctypes
from ctypes import wintypes
import os
import io
import locale
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile


class LocalDemoError(ValueError):
    def __init__(self, message, program=None, returncode=None):
        super().__init__(message)
        self.program, self.returncode = program, returncode


_job_handle = None


def contain_children():
    """The OS terminates our children even if the demo EXE crashes/is killed."""
    global _job_handle
    if _job_handle is not None:
        return
    if sys.platform != 'win32':
        raise LocalDemoError('Místní ukázka je určena pro Windows.')
    class Basic(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                    ('flags', wintypes.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t),
                    ('process_limit', wintypes.DWORD), ('affinity', ctypes.c_size_t),
                    ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
    class Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in
                    ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
    class Extended(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', Counters), ('process_memory', ctypes.c_size_t),
                    ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    limits = Extended(); limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        if handle: kernel.CloseHandle(handle)
        raise LocalDemoError('Windows nepovolil připravit místní ukázku.')
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        kernel.CloseHandle(handle)
        raise LocalDemoError('Windows nepovolil spustit pomocné procesy ukázky.')
    # Do not explicitly close this handle: the current process belongs to it.
    # Windows closes it at process exit, after our normal graceful shutdown.
    _job_handle = handle


@contextmanager
def external_libraries():
    # PostgreSQL must load its own DLLs, not psycopg/PyInstaller's OpenSSL build.
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    buffer = ctypes.create_unicode_buffer(32768)
    kernel.GetDllDirectoryW(len(buffer), buffer)
    kernel.SetDllDirectoryW(None)
    try:
        yield
    finally:
        kernel.SetDllDirectoryW(buffer.value or None)


class DemoProfile:
    def __init__(self, port, dbname, user, password):
        self.port, self.dbname, self.user, self._password = port, dbname, user, password

    def connect(self, password=None):
        import psycopg
        return psycopg.connect(host='127.0.0.1', hostaddr='127.0.0.1', port=self.port,
            dbname=self.dbname, user=self.user, password=self._password if password is None else password,
            sslmode='disable', connect_timeout=3, autocommit=True,
            options='-c statement_timeout=300000 -c lock_timeout=10000')


class LocalDemo:
    schema = 'turto_pilot_local_demo'

    def __init__(self):
        self.folder = None
        self.cluster = None
        self.server_pid = None
        self.log = None
        self.profiles = {}
        self.port = None
        self.phase = 'Připravuji místní ukázku…'
        self.failure_log = ''
        self.failure = None
        self.report_path = None
        self._secrets = []

    def start(self, progress=lambda message: None):
        try:
            return self._start(progress)
        except Exception as exc:
            self.capture_failure(exc)
            try:
                self.stop()
            except Exception as cleanup:
                self.failure['cleanup_error_type'] = type(cleanup).__name__
            try:
                from .diagnostics import save_report
                self.report_path = save_report(self.failure, 'mistni-ukazka')
            except Exception as reporting:
                self.failure['report_save_error_type'] = type(reporting).__name__
            raise

    def _start(self, progress):
        from psycopg import sql
        from . import demo, directory
        contain_children()
        runtime = Path(sys.executable).resolve().parent / 'postgresql'
        for name in ('postgres.exe', 'initdb.exe', 'pg_ctl.exe'):
            if not (runtime / 'bin' / name).is_file():
                raise LocalDemoError('Chybí složka postgresql. Rozbalte celý balíček včetně všech složek.')
        parent = Path(os.environ['LOCALAPPDATA']) / 'TURTO' / 'CRM-Local-Demo'
        if ctypes.windll.kernel32.GetDriveTypeW(str(parent.anchor)) != 3:
            raise LocalDemoError('Místní ukázka potřebuje místní disk pro data uživatele Windows.')
        parent.mkdir(parents=True, exist_ok=True)
        self.folder = Path(tempfile.mkdtemp(prefix='session-', dir=parent))
        self.cluster = self.folder / 'database'
        self.bin = runtime / 'bin'
        self.env = {key: value for key, value in os.environ.items() if not key.upper().startswith('PG')}
        system = Path(os.environ['SystemRoot'])
        self.env['PATH'] = os.pathsep.join(map(str, (self.bin, system / 'System32', system)))
        self.log = (self.folder / 'startup.log').open('ab', buffering=0)
        # Python's private temp-directory ACL can belong to Administrators
        # when elevated. PostgreSQL drops that group. Explicitly grant only
        # the current user SID on OUR NEW directory, inherited by its files.
        # No company path or pre-existing user directory is reconfigured.
        with external_libraries():
            identity = subprocess.run([str(system / 'System32/whoami.exe'), '/user', '/fo', 'csv', '/nh'],
                capture_output=True, check=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            sid = next(csv.reader(io.StringIO(identity.stdout.decode(errors='replace'))))[1]
            if not sid.startswith('S-1-') or any(c not in 'S-0123456789' for c in sid):
                raise LocalDemoError('Nepodařilo se ověřit místního uživatele Windows.')
            subprocess.run([str(system / 'System32/icacls.exe'), str(self.folder), '/grant:r',
                            '*' + sid + ':(OI)(CI)F'], check=True, stdout=self.log, stderr=self.log,
                timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        # Supply an existing empty directory. initdb otherwise walks every
        # parent while creating it, including private Windows profile roots.
        self.cluster.mkdir()
        self.phase = 'Připravuji testovací databázi…'; progress(self.phase)
        secret = secrets.token_urlsafe(36)
        self._secrets.append(secret)
        password_file = self.folder / 'initial-password.txt'
        password_file.write_text(secret + '\n', encoding='ascii')
        try:
            self.command('initdb.exe', '-D', str(self.cluster), '-U', 'demo_owner',
                '--auth=scram-sha-256', '--encoding=UTF8', '--locale=C', '--pwfile=' + str(password_file), timeout=120)
        finally:
            password_file.unlink(missing_ok=True)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            self.port = listener.getsockname()[1]
        with (self.cluster / 'postgresql.conf').open('a', encoding='utf-8') as config:
            config.write(f"\nlisten_addresses = '127.0.0.1'\nport = {self.port}\nssl = off\n"
                         "unix_socket_directories = ''\nshared_buffers = '32MB'\nmax_connections = 20\n")
        # No replication, trust authentication, non-loopback rules or external configuration.
        (self.cluster / 'pg_hba.conf').write_text(
            'host all all 127.0.0.1/32 scram-sha-256\n', encoding='ascii')
        self.command('pg_ctl.exe', '-D', str(self.cluster), '-l', str(self.folder / 'server.log'),
                     '-w', '-t', '40', 'start', timeout=50)
        self.server_pid = int((self.cluster / 'postmaster.pid').read_text().splitlines()[0])
        owner = DemoProfile(self.port, 'postgres', 'demo_owner', secret)
        with owner.connect() as con:
            con.execute('CREATE DATABASE turto_local_demo')
        owner = DemoProfile(self.port, 'turto_local_demo', 'demo_owner', secret)
        self.phase = 'Načítám ukázkové společnosti a zkušební účty…'; progress(self.phase)
        demo.prepare(owner, self.schema)
        people = demo.users(owner, self.schema)
        for role, title in (('editor1', 'Pilot – editor'), ('editor2', 'Pilot – editor'), ('reader', 'Pilot – čtenář')):
            login, password = 'demo_' + role, secrets.token_urlsafe(36)
            self._secrets.append(password)
            with owner.connect() as con:
                con.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE '
                    'NOREPLICATION NOBYPASSRLS PASSWORD {}').format(sql.Identifier(login), sql.Literal(password)))
            uid = next(person['id'] for person in people if person['name'] == title)
            directory.authorize(owner, self.schema, login, uid)
            self.profiles[role] = DemoProfile(self.port, 'turto_local_demo', login, password)
        return self

    def capture_failure(self, exc):
        from .diagnostics import redact
        logs = []
        if self.folder:
            for name in ('startup.log', 'server.log'):
                try:
                    raw = (self.folder / name).read_bytes()
                    try:
                        text = raw.decode('utf-8')
                    except UnicodeDecodeError:
                        text = raw.decode(locale.getpreferredencoding(False), errors='replace')
                    # Redact BEFORE truncation so a boundary cannot expose half a password.
                    logs.append(name + ':\n' + redact(text, self._secrets)[-6000:])
                except OSError:
                    pass
        self.failure_log = '\n'.join(logs)
        self.failure = {'format': 1, 'kind': 'local-demo-startup', 'phase': self.phase,
                        'error_type': type(exc).__name__, 'message': redact(str(exc), self._secrets),
                        'program': getattr(exc, 'program', None), 'returncode': getattr(exc, 'returncode', None),
                        'startup_log': self.failure_log, 'company_data_read': False}

    def command(self, name, *args, timeout=30):
        with external_libraries():
            # initdb invokes postgres through cmd.exe after restricting its token.
            # Keep its CWD in the readable runtime, not a private temporary folder.
            result = subprocess.run([str(self.bin / name), *args], cwd=self.bin, env=self.env,
                stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log, timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            code = result.returncode & 0xffffffff
            hint = (' Windows nenašel potřebnou knihovnu DLL.' if code == 0xc0000135 else '')
            raise LocalDemoError(f'Příprava místní databáze selhala: {name}, kód {code:#010x}.' + hint,
                                 program=name, returncode=code)

    def client(self, role):
        from .client import DirectoryClient
        return DirectoryClient(self.profiles[role], self.schema)

    def stop(self):
        self.profiles.clear()
        self._secrets.clear()
        if self.cluster and (self.cluster / 'postmaster.pid').is_file():
            self.command('pg_ctl.exe', '-D', str(self.cluster), '-m', 'fast', '-w', '-t', '20', 'stop', timeout=25)
        if self.log:
            self.log.close(); self.log = None
        if self.folder and self.folder.exists():
            # Only this invocation's freshly created directory; never scan/delete other sessions.
            shutil.rmtree(self.folder)
