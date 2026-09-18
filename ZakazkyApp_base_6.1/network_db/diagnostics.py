"""Small, explicit reports; never collect passwords, environment or CRM data."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import time
import uuid


def save_report(report, prefix):
    folder = Path(os.environ['LOCALAPPDATA']) / 'TURTO' / 'CRM-Diagnostics'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (prefix + '-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.json')
    with path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return path


def redact(text, secrets):
    for secret in sorted((value for value in secrets if value), key=len, reverse=True):
        text = text.replace(secret, '[HESLO VYNECHÁNO]')
    return text


def probe(host, port, timeout=3):
    """Connect only to the requested TCP port, without authentication or writes."""
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {'reachable': True, 'elapsed_ms': round((time.monotonic() - started) * 1000)}
    except OSError as exc:
        return {'reachable': False, 'error_type': type(exc).__name__,
                'error_code': getattr(exc, 'winerror', None) or exc.errno}


def check_network(host, port=5432):
    host = host.strip()
    if not host or any(char in host for char in '/\\ \t\n\r') or not 1 <= int(port) <= 65535:
        raise ValueError('Zadejte IP adresu nebo název serveru a port 1 až 65535.')
    return {'format': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
            'server': host, 'database_port': int(port), 'database_tcp': probe(host, int(port)),
            'file_share_tcp': probe(host, 445),
            'scope': 'TCP dostupnost. Neověřuje přihlášení, certifikát, sdílenou složku ani nastavení VPN.'}


def network_summary(report):
    database = 'dostupný' if report['database_tcp']['reachable'] else 'nedostupný'
    share = 'dostupný' if report['file_share_tcp']['reachable'] else 'nedostupný'
    return (f"Server: {report['server']}\n"
            f"Databázový port {report['database_port']}: {database}\n"
            f"Port souborového serveru 445: {share}\n\n"
            'Dostupný port ještě nepotvrzuje funkční přihlášení do CRM.\n'
            'Nedostupný port může znamenat vypnutou službu, jiný port nebo omezení sítě/VPN.\n'
            'Tato kontrola nemění síť, server ani data.')
