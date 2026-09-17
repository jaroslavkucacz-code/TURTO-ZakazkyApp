#!/usr/bin/env python3
"""Mail snapshots, explicit user profiles, defaults and real Windows dialog events."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "ZakazkyApp_base_6.1"))
spec = importlib.util.spec_from_file_location("previous_checks", REPO / "scripts/validate-827-processing-catalogs.py")
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
from price_lists_domain.platform import request_mail as mail


def seed(M):
    with M.db() as con:
        con.execute("INSERT OR IGNORE INTO users(name,active) VALUES('829 Alena',1),('829 Bára',1),('829 Old',0),('Admin',1),(' tEsT ',1),('Testovací technik',1)")
        supplier = con.execute("INSERT INTO companies(short_name,official_name,is_supplier) VALUES('829 Dodavatel','829 Dodavatel',1)").lastrowid
        con.execute("INSERT INTO materials(name) VALUES('829 Nosník')")
        con.execute("INSERT INTO actions(name) VALUES('829 Akce')")
    mail.save_profile(M, '829 Alena', 'Dobrý den,\n\nProsím o nabídku.\nAlena', mail.DEFAULT_BODY)
    mail.save_profile(M, '829 Bára', 'Dobrý den,\nBára', mail.DEFAULT_BODY)
    M.set_setting('active_user', '829 Bára')
    M.set_setting('include_project_default', '1')
    return supplier


def source_checks(td):
    M = previous.prepare(td)
    supplier = seed(M)
    with M.db() as con:
        con.execute('ALTER TABLE requests DROP COLUMN mail_body')
        con.execute('ALTER TABLE requests DROP COLUMN urgent')
        rid = con.execute("INSERT INTO requests(company_id,assigned_user,mail_subject) VALUES(?, '829 Alena', 'Původní předmět')", (supplier,)).lastrowid
    M.ensure_schema(); M.ensure_schema()
    import runtime_bootstrap
    runtime_bootstrap.apply_all(M)
    M.ensure_schema()
    with M.db() as con:
        row = con.execute('SELECT * FROM requests WHERE id=?', (rid,)).fetchone()
        assert row['mail_body'] is None and row['urgent'] == 0
        names = mail.users(con)
        assert '829 Alena' in names and '829 Bára' in names and 'Testovací technik' in names
        assert not any(mail.technical_user(name) for name in names) and '829 Old' not in names
        previous.rejects(lambda: mail.validate_user(con, 'Admin'))
        previous.rejects(lambda: mail.validate_user(con, 'TEST'))
        previous.rejects(lambda: mail.validate_user(con, '829 Al'))
        assert mail.validate_user(con, '829 Old', '829 Old') == '829 Old'
    assert mail.body_for_request(M, row) == mail.profile(M, '829 Alena')
    assert mail.body_for_request(M, {'mail_body': '', 'assigned_user': '829 Alena'}) == ''
    local = SimpleNamespace(manage_code_lists=lambda: None, active_user=SimpleNamespace(get=lambda: '829 Alena'))
    assert mail.default_user(M, local, names) == '829 Alena'
    local.active_user.get = lambda: 'TEST'
    assert mail.default_user(M, local, names) == ''
    old = mail.profile(M, '829 Alena')
    mail.save_profile(M, '829 Alena', '', old)
    assert mail.profile(M, '829 Alena') == '' and mail.profile(M, '829 Bára') == 'Dobrý den,\nBára'
    previous.rejects(lambda: mail.save_profile(M, '829 Alena', 'stale', old))
    previous.rejects(lambda: mail.save_profile(M, 'Admin', 'invalid', mail.DEFAULT_BODY))
    M.ensure_schema()
    assert mail.profile(M, '829 Alena') == ''
    for include in (False, True):
        base = M.build_subject('Dodavatel', 'Akce', 'Nosník', '2026-09-17', include)
        assert ('Akce' in base) == include
        urgent = mail.with_urgency(base, True)
        assert urgent == 'SPĚCHÁ! ' + base
        assert mail.with_urgency(urgent, True) == urgent
        assert mail.with_urgency(urgent, False) == base
    assert not mail.flag(0) and not mail.flag('0') and mail.flag(1)
    body = 'Dobrý den,\n\nCenová nabídka „A&B“ <text>\nDěkuji,\nAlena'
    # Exercise both transports without opening Outlook or sending a message.
    with patch.object(M.sys, 'platform', 'win32'), patch.object(M.subprocess, 'run') as run:
        run.return_value = SimpleNamespace(returncode=0, stdout='', stderr='')
        assert M.open_mail_draft(['a@example.invalid'], 'SPĚCHÁ! Poptávka', body=body)
        env = run.call_args.kwargs['env']
        assert env['ZAK_BODY'] == body.replace('\n', '\r\n')
        assert env['ZAK_SUBJECT'] == 'SPĚCHÁ! Poptávka'
        script = run.call_args.args[0][-1]
        assert '$existing=$mail.HTMLBody' in script and '$editor.Range(0,0)' in script
        assert '$mail.Send(' not in script
    with patch.object(M.sys, 'platform', 'linux'), patch.object(M.webbrowser, 'open') as browser:
        assert M.open_mail_draft([], 'Předmět', body=body)
        query = parse_qs(urlsplit(browser.call_args.args[0]).query, keep_blank_values=True)
        assert query['body'] == [body.replace('\n', '\r\n')]
        assert M.open_mail_draft([], 'Prázdný', body='')
        assert parse_qs(urlsplit(browser.call_args.args[0]).query, keep_blank_values=True)['body'] == ['']
    with M.db() as con:
        con.execute('UPDATE requests SET mail_body=?,urgent=1 WHERE id=?', (body, rid))
    fake = SimpleNamespace(selected_id=lambda *a: rid, request_tree=None)
    with patch.object(M, 'open_mail_draft') as draft:
        M.App.mail_selected(fake)
        assert draft.call_args.kwargs['body'] == body
        assert draft.call_args.args[1] == 'SPĚCHÁ! Původní předmět'
    with M.db() as con:
        assert tuple(con.execute('SELECT mail_body,urgent FROM requests WHERE id=?', (rid,)).fetchone()) == (body, 1)
    print('8.0.29: additive migration, isolated profiles, explicit/stale saves, user validation, subject flags, snapshots and both draft transports OK', flush=True)


def ui_checks(td):
    M = previous.prepare(td, runtime=True)
    supplier = seed(M)
    M.App.maybe_show_morning_overview = lambda self: None
    errors, warnings = [], []
    M.messagebox.showinfo = lambda *a, **k: None
    M.messagebox.showwarning = lambda *a, **k: warnings.append(a)
    M.messagebox.showerror = lambda *a, **k: errors.append(a)
    M.messagebox.askyesnocancel = lambda *a, **k: False
    M.App.report_callback_exception = lambda self, *exc: errors.append(str(exc))
    root = M.App()
    settle = previous.settle
    try:
        settle(root, 4)
        root.active_user.set('829 Alena')
        M.set_setting('active_user', '829 Bára')  # Another client must not choose our requester.
        d = M.RequestDialog(root); settle(root)
        assert d.assigned.get() == '829 Alena'
        assert not d.include.get() and not d.urgent.get()
        assert not any(mail.technical_user(name) for name in d.user_names)
        assert d.mail_body.get('1.0', 'end-1c') == mail.profile(M, '829 Alena')
        d.assigned.set('829 Bára'); settle(root)
        assert d.mail_body.get('1.0', 'end-1c') == mail.profile(M, '829 Bára')
        custom = 'Dobrý den,\n\nTato poptávka má vlastní text.\nDěkuji.'
        d._set_mail_body(custom)
        d.assigned.set('829 Alena'); settle(root)
        assert d.mail_body.get('1.0', 'end-1c') == custom
        d.mail_body.focus_force(); d.mail_body.mark_set('insert', 'end-1c')
        d.mail_body.event_generate('<Return>'); settle(root)
        assert d.winfo_exists() and d.result is None
        assert d.mail_body.get('1.0', 'end-1c') == custom + '\n'
        d.company.set('829 Dodavatel'); d.item.set('829 Nosník'); d.action.set('829 Akce'); settle(root)
        assert '829 Akce' not in d.subject.get()
        d.include_check.invoke(); d.urgent_check.invoke(); settle(root)
        assert d.subject.get().startswith('SPĚCHÁ! Poptávka TURTO') and '829 Akce' in d.subject.get()
        d.update_preview(); assert d.subject.get().count('SPĚCHÁ!') == 1
        d.urgent_check.invoke(); assert not d.subject.get().startswith('SPĚCHÁ!')
        d.urgent_check.invoke()
        d.assigned.set('Admin'); d.ok(); settle(root)
        assert d.result is None and warnings
        d.assigned.set('829 Alena'); d.ok(); settle(root)
        assert d.result and d.result['urgent'] == 1 and d.result['mail_body'] == custom + '\n', warnings
        root.save_request(d); settle(root)
        with M.db() as con:
            rid = con.execute('SELECT id FROM requests WHERE company_id=? ORDER BY id DESC', (supplier,)).fetchone()[0]
            row = con.execute('SELECT * FROM requests WHERE id=?', (rid,)).fetchone()
        assert row['mail_body'] == custom + '\n' and row['urgent'] == 1
        assert mail.profile(M, '829 Alena') != custom + '\n', 'Ordinary Save changed the user default'
        # Explicit profile cancel/save, with real Text Enter preserving the dialog.
        editor = mail.ProfileDialog(root, M, '829 Alena'); settle(root)
        editor.body.delete('1.0', 'end'); editor.body.insert('1.0', 'Neuložit')
        editor.destroy(); settle(root)
        assert mail.profile(M, '829 Alena') != 'Neuložit'
        editor = mail.ProfileDialog(root, M, '829 Alena'); settle(root)
        editor.body.delete('1.0', 'end'); editor.body.insert('1.0', 'Nový výchozí text')
        editor.save(); settle(root)
        assert mail.profile(M, '829 Alena') == 'Nový výchozí text'
        reopened = M.RequestDialog(root, rid=rid); settle(root)
        assert reopened.include.get() and reopened.urgent.get()
        assert reopened.mail_body.get('1.0', 'end-1c') == custom + '\n'
        reopened.include_check.invoke(); reopened.urgent_check.invoke()
        reopened.ok(); settle(root)
        # Exercise the actual edit SQL with the edited dialog result.
        original_dialog = M.RequestDialog
        with patch.object(M, 'RequestDialog', return_value=reopened), patch.object(root, 'wait_window'), patch.object(root, 'selected_id', return_value=rid):
            root.edit_request()
        settle(root)
        saved = original_dialog(root, rid=rid); settle(root)
        assert not saved.include.get() and not saved.urgent.get()
        assert saved.mail_body.get('1.0', 'end-1c') == custom + '\n'
        saved.destroy(); settle(root)
        new = M.RequestDialog(root); settle(root)
        assert not new.include.get() and not new.urgent.get()
        assert new.mail_body.get('1.0', 'end-1c') == 'Nový výchozí text'
        new.destroy(); settle(root)
        assert M.get_setting('include_project_default') == '1', 'Dialog still writes global defaults'
        mivo = M.RequestDialog(root, pre_company='MIVO'); settle(root)
        assert mivo.is_mivo and not mivo.include.get() and not mivo.urgent.get()
        mivo.subject.set('Vlastní předmět MIVO')
        mivo.urgent_check.invoke(); settle(root)
        assert mivo.subject.get() == 'SPĚCHÁ! Vlastní předmět MIVO'
        mivo.update_preview(); assert mivo.subject.get() == 'SPĚCHÁ! Vlastní předmět MIVO'
        mivo.urgent_check.invoke(); assert mivo.subject.get() == 'Vlastní předmět MIVO'
        mivo.destroy(); settle(root)
        root.active_user.set('TEST')
        technical = M.RequestDialog(root); settle(root)
        assert technical.assigned.get() == '' and not any(mail.technical_user(name) for name in technical.user_names)
        technical.destroy(); settle(root)
        assert not errors, errors
        print('8.0.29: Windows local user, excluded accounts, editable multiline body, profile save/cancel, independent snapshots, new/edit defaults and MIVO urgency OK', flush=True)
    finally:
        for job in root.tk.splitlist(root.tk.call('after', 'info')):
            try: root.after_cancel(job)
            except Exception: pass
        try: root.destroy()
        except (M.tk.TclError, TypeError): pass


if __name__ == '__main__':
    if '--source-worker' in sys.argv:
        source_checks(sys.argv[-1])
    elif '--ui-worker' in sys.argv:
        ui_checks(sys.argv[-1])
    else:
        with tempfile.TemporaryDirectory(prefix='turto-request-mail-829-') as td:
            subprocess.run([sys.executable, '-B', __file__, '--source-worker', str(Path(td) / 'source')], check=True)
            if '--source-only' not in sys.argv:
                subprocess.run([sys.executable, '-B', __file__, '--ui-worker', str(Path(td) / 'ui')], check=True)
