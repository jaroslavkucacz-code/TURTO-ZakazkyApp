from pathlib import Path


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly one anchor, found {count}')
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# post_baseline.py: one canonical Explorer folder foreground helper.
# -----------------------------------------------------------------------------
p = Path('post_baseline.py')
s = p.read_text(encoding='utf-8')
anchor = '''    def set_archive_root(app, path):\n        data = load_cfg()\n        data.setdefault('offer_archive_dir_by_user', {})[active_user(app)] = str(Path(path))\n        save_cfg(data)\n\n'''
helper = anchor + '''    def show_offer_archive_folder(app, folders):\n        \"\"\"Open the resulting offer folder, or foreground its existing Explorer window.\"\"\"\n        try:\n            import os\n            import subprocess\n            import sys\n\n            if not sys.platform.startswith('win'):\n                return False\n\n            if isinstance(folders, (str, Path)):\n                folders = [folders]\n            unique = []\n            seen = set()\n            for raw in folders or []:\n                try:\n                    path = Path(str(raw))\n                    if not path.is_dir():\n                        continue\n                    key = os.path.normcase(os.path.normpath(os.path.abspath(str(path))))\n                    if key in seen:\n                        continue\n                    seen.add(key)\n                    unique.append(path)\n                except Exception:\n                    pass\n            if not unique:\n                return False\n\n            # One imported offer -> show its exact folder. A multi-offer batch can\n            # create several sibling folders, so show their configured archive root.\n            target = unique[0] if len(unique) == 1 else archive_root(app)\n            target = Path(target)\n            if not target.is_dir():\n                return False\n            target_key = os.path.normcase(\n                os.path.normpath(os.path.abspath(str(target)))\n            )\n\n            def foreground_existing():\n                pythoncom = None\n                try:\n                    import pythoncom\n                    import win32com.client\n                    import win32con\n                    import win32gui\n\n                    pythoncom.CoInitialize()\n                    shell = win32com.client.Dispatch('Shell.Application')\n                    for window in shell.Windows():\n                        try:\n                            current = str(window.Document.Folder.Self.Path or '')\n                            current_key = os.path.normcase(\n                                os.path.normpath(os.path.abspath(current))\n                            )\n                            if current_key != target_key:\n                                continue\n                            hwnd = int(getattr(window, 'HWND', 0) or 0)\n                            if not hwnd:\n                                continue\n                            try:\n                                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)\n                            except Exception:\n                                pass\n                            try:\n                                win32gui.SetWindowPos(\n                                    hwnd,\n                                    win32con.HWND_TOP,\n                                    0, 0, 0, 0,\n                                    win32con.SWP_NOMOVE\n                                    | win32con.SWP_NOSIZE\n                                    | win32con.SWP_SHOWWINDOW,\n                                )\n                            except Exception:\n                                pass\n                            try:\n                                win32gui.SetForegroundWindow(hwnd)\n                            except Exception:\n                                try:\n                                    win32gui.BringWindowToTop(hwnd)\n                                except Exception:\n                                    pass\n                            return True\n                        except Exception:\n                            continue\n                except Exception:\n                    return False\n                finally:\n                    try:\n                        if pythoncom is not None:\n                            pythoncom.CoUninitialize()\n                    except Exception:\n                        pass\n                return False\n\n            if foreground_existing():\n                return True\n\n            try:\n                os.startfile(str(target))\n            except Exception:\n                try:\n                    subprocess.Popen(['explorer.exe', str(target)])\n                except Exception:\n                    return False\n\n            # Explorer may need a moment to materialize the new window. Refocus it\n            # after launch so CRM never leaves the newly opened folder behind itself.\n            try:\n                app.after(350, foreground_existing)\n                app.after(900, foreground_existing)\n            except Exception:\n                pass\n            return True\n        except Exception:\n            return False\n\n    M.show_offer_archive_folder = show_offer_archive_folder\n\n'''
s = replace_once(s, anchor, helper, 'post_baseline explorer helper')

batch_info = '''            messagebox.showinfo(\n                'Zpracování cenových nabídek',\n                text,\n                parent=self,\n            )\n'''
batch_new = batch_info + '''            if state['archives'] and not state['cancel']:\n                show_offer_archive_folder(self, state['archives'])\n'''
s = replace_once(s, batch_info, batch_new, 'post_baseline batch completion')
p.write_text(s, encoding='utf-8')


# -----------------------------------------------------------------------------
# v631_diskdrop.py: Outlook virtual PDF / whole MSG direct path uses the same
# Explorer helper as the normal batch runner.
# -----------------------------------------------------------------------------
p = Path('ZakazkyApp_base_6.1/v631_diskdrop.py')
s = p.read_text(encoding='utf-8')
s = replace_once(
    s,
    '''        attachments = 0\n        excel_files = 0\n\n''',
    '''        attachments = 0\n        excel_files = 0\n        archive_folders = []\n\n''',
    'v631 archive state',
)

msg_anchor = '''                    result = M.process_offer_msg(app, path)\n                    _log(f'{source_label} MSG processing end: {path.name}')\n                    messages += 1\n'''
msg_new = '''                    result = M.process_offer_msg(app, path)\n                    _log(f'{source_label} MSG processing end: {path.name}')\n                    if isinstance(result, dict) and result.get('archive_folder'):\n                        archive_folders.append(result['archive_folder'])\n                    messages += 1\n'''
s = replace_once(s, msg_anchor, msg_new, 'v631 MSG archive capture')

pdf_anchor = '''                    if isinstance(result, dict):\n                        excel_files += len(result.get('excel_files') or [])\n                    good.append(result)\n'''
pdf_new = '''                    if isinstance(result, dict):\n                        excel_files += len(result.get('excel_files') or [])\n                        if result.get('archive_folder'):\n                            archive_folders.append(result['archive_folder'])\n                    good.append(result)\n'''
s = replace_once(s, pdf_anchor, pdf_new, 'v631 PDF archive capture')

info_anchor = '''            messagebox.showinfo(\n                'Nabídky – ' + source_label.lower(),\n                text,\n                parent=app,\n            )\n        except Exception:\n            pass\n        return good\n'''
info_new = '''            messagebox.showinfo(\n                'Nabídky – ' + source_label.lower(),\n                text,\n                parent=app,\n            )\n        except Exception:\n            pass\n        if archive_folders:\n            try:\n                opener = getattr(M, 'show_offer_archive_folder', None)\n                if callable(opener):\n                    opener(app, archive_folders)\n            except Exception:\n                pass\n        return good\n'''
s = replace_once(s, info_anchor, info_new, 'v631 direct completion')
p.write_text(s, encoding='utf-8')


# -----------------------------------------------------------------------------
# app.py: the actual Outlook draft owner activates its Inspector after the draft
# is fully populated. No second mail mechanism is introduced.
# -----------------------------------------------------------------------------
p = Path('ZakazkyApp_base_6.1/app.py')
s = p.read_text(encoding='utf-8')
mail_anchor = '''  $mail.HTMLBody=\"<div>\"+$safe+\"</div>\"+$existing\n}\n\"\"\"\n'''
mail_new = '''  $mail.HTMLBody=\"<div>\"+$safe+\"</div>\"+$existing\n}\n# The Inspector may lose foreground while CRM finishes its synchronous call.\n# Activate the completed draft once more so it is immediately visible to user.\ntry {\n  $mail.GetInspector.Activate()\n} catch {}\n\"\"\"\n'''
s = replace_once(s, mail_anchor, mail_new, 'app Outlook draft activation')
p.write_text(s, encoding='utf-8')


Path('release_version.txt').write_text('6.3.13\n', encoding='utf-8')
Path('release_notes.txt').write_text(
    '''• Po dokončení importu cenových nabídek CRM automaticky zobrazí složku s exportem v Průzkumníkovi. Při jednom importu se otevře konkrétní složka nabídky; při dávce s více cílovými složkami se otevře společný kořen archivu.\n'''
    '''• Pokud je cílová složka už v Průzkumníkovi otevřená, CRM neotevírá další duplicitní okno: najde existující Explorer okno podle skutečné cesty, obnoví ho z minimalizace a vytáhne ho dopředu.\n'''
    '''• Stejný mechanismus se používá pro běžný PDF/MSG batch i pro PDF přílohu nebo celý e-mail přetažený přímo z Outlooku.\n'''
    '''• Při vytvoření e-mailu s Poptávkou se po naplnění příjemců, předmětu, textu a podpisu znovu aktivuje přímo Outlook Inspector daného konceptu, takže koncept zůstane navrchu a je hned vidět.\n'''
    '''• Databáze, parsery, Excel exporty, názvy archivů a logika samotného zpracování nabídek se nemění.\n''',
    encoding='utf-8',
)

# Static invariants for the targeted UX change.
base = Path('post_baseline.py').read_text(encoding='utf-8')
v631 = Path('ZakazkyApp_base_6.1/v631_diskdrop.py').read_text(encoding='utf-8')
app = Path('ZakazkyApp_base_6.1/app.py').read_text(encoding='utf-8')
assert 'M.show_offer_archive_folder = show_offer_archive_folder' in base
assert "Shell.Application" in base
assert 'SetForegroundWindow' in base
assert "show_offer_archive_folder(self, state['archives'])" in base
assert 'archive_folders = []' in v631
assert "getattr(M, 'show_offer_archive_folder', None)" in v631
assert '$mail.GetInspector.Activate()' in app
