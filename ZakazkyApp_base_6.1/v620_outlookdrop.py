# TURTO CRM 6.0.20 - drag & drop into Nabidky incl. direct Outlook selection fallback
import os, re, tempfile, hashlib
from pathlib import Path

def apply(M):
    # Preserve complete source MSG for later reprocessing/audit.
    try:
        with M.db() as c:
            if not M.has_column(c,'offer_source_messages','source_blob'):
                c.execute('ALTER TABLE offer_source_messages ADD COLUMN source_blob BLOB')
    except Exception:
        pass

    def _store_source_blob(path, message_id=None):
        try:
            p=Path(path); raw=p.read_bytes(); h=hashlib.sha256(raw).hexdigest()
            with M.db() as c:
                if message_id:
                    c.execute('UPDATE offer_source_messages SET source_blob=? WHERE id=?',(M.sqlite3.Binary(raw),message_id))
                else:
                    c.execute('UPDATE offer_source_messages SET source_blob=? WHERE source_hash=?',(M.sqlite3.Binary(raw),h))
        except Exception:
            pass

    # Public wrapper used by drag/drop. Existing file-picker import remains compatible.
    old_process_msg=getattr(M,'process_offer_msg',None)
    if old_process_msg:
        def process_msg(app,path):
            r=old_process_msg(app,path)
            _store_source_blob(path,(r or {}).get('message_id'))
            return r
        M.process_offer_msg=process_msg

    def _safe_filename(text, fallback='outlook_zprava'):
        s=re.sub(r'[<>:"/\\|?*\x00-\x1f]+','_',str(text or '')).strip(' ._')
        return (s[:120] or fallback)+'.msg'

    def _process_paths(app, paths, parent=None):
        from tkinter import messagebox
        good=[];errors=[];messages=0;attachments=0
        for raw in paths:
            p=Path(str(raw).strip().strip('{}"'))
            if not p.exists():
                errors.append(f'{p}: soubor nebyl nalezen');continue
            try:
                ext=p.suffix.lower()
                if ext=='.msg':
                    r=M.process_offer_msg(app,p);messages+=1;attachments+=int((r or {}).get('attachments') or 0);good.extend((r or {}).get('offers') or [])
                    errors.extend((r or {}).get('errors') or [])
                elif ext=='.pdf':good.append(M.process_offer_pdf(app,p))
                else:errors.append(f'{p.name}: nepodporovaný formát')
            except Exception as e:errors.append(f'{p.name}: {e}')
        try:app.refresh_offers()
        except Exception:pass
        text=f'Zpracováno. Nabídky: {len(good)}'
        if messages:text+=f'   •   MSG: {messages}   •   přílohy: {attachments}'
        if errors:text+='\n\nChyby:\n'+'\n'.join(errors[:12])
        messagebox.showinfo('Nabídky – přetažení',text,parent=parent or app)
        return good

    def _save_selected_outlook_items(app):
        """When Outlook supplies a virtual drag instead of a filesystem path,
        save the currently selected Outlook MailItem(s) as temporary .msg files.
        This is also exposed as a guaranteed manual fallback button.
        """
        if not os.name=='nt':
            raise RuntimeError('Přímý import z Outlooku je dostupný ve Windows.')
        try:
            import win32com.client
        except Exception as e:
            raise RuntimeError('Chybí pywin32 pro přímý přenos z Outlooku.') from e
        try:
            try:ol=win32com.client.GetActiveObject('Outlook.Application')
            except Exception:ol=win32com.client.Dispatch('Outlook.Application')
            explorer=ol.ActiveExplorer()
            sel=explorer.Selection if explorer is not None else None
            count=int(sel.Count) if sel is not None else 0
            if count<1:raise RuntimeError('V Outlooku není vybraný žádný e-mail.')
            td=tempfile.TemporaryDirectory(prefix='turto_outlook_drop_');paths=[]
            for i in range(1,count+1):
                item=sel.Item(i)
                # Class 43 = MailItem. Other Outlook items are skipped.
                try:
                    if int(getattr(item,'Class',0))!=43:continue
                except Exception:pass
                subject=getattr(item,'Subject','') or f'outlook_{i}'
                p=Path(td.name)/_safe_filename(subject,f'outlook_{i}')
                # olMSG = 3. Outlook creates a real MSG that goes through the same parser as file import.
                item.SaveAs(str(p),3);paths.append(p)
            if not paths:
                td.cleanup();raise RuntimeError('Výběr Outlooku neobsahuje zpracovatelný e-mail.')
            return td,paths
        except Exception as e:
            raise RuntimeError(f'Outlook zprávu se nepodařilo převzít: {e}') from e

    def _import_outlook_selection(app,parent=None):
        from tkinter import messagebox
        td=None
        try:
            td,paths=_save_selected_outlook_items(app)
            return _process_paths(app,paths,parent)
        except Exception as e:
            messagebox.showerror('Přenos z Outlooku',str(e),parent=parent or app);return []
        finally:
            try:
                if td:td.cleanup()
            except Exception:pass

    def _split_drop_data(app,data):
        # tkdnd returns a Tcl list; paths containing spaces are wrapped in braces.
        try:return list(app.tk.splitlist(data))
        except Exception:
            s=str(data or '').strip()
            return [s] if s else []

    def _handle_drop(app,event,zone=None):
        """Accept normal PDF/MSG filesystem drops. If Outlook gives only a virtual
        object/no usable path, use the Outlook selection and SaveAs(.msg).
        """
        from tkinter import messagebox
        data=getattr(event,'data','') or ''
        items=_split_drop_data(app,data)
        existing=[]
        for x in items:
            p=Path(str(x).strip().strip('{}"'))
            if p.exists() and p.suffix.lower() in ('.msg','.pdf'):existing.append(p)
        if existing:
            _process_paths(app,existing,zone or app);return 'break'
        # Direct Outlook drag often arrives as a virtual FileGroupDescriptor rather than a path.
        _import_outlook_selection(app,zone or app)
        return 'break'

    def _register_drop(app,widget):
        """Load tkdnd into the existing Tk interpreter without replacing App's Tk class."""
        try:
            from tkinterdnd2 import TkinterDnD, DND_FILES, DND_TEXT
            TkinterDnD._require(app)
            app.tk.call('tkdnd::drop_target','register',widget._w,DND_FILES,DND_TEXT)
            widget.bind('<<Drop>>',lambda e:_handle_drop(app,e,widget),add='+')
            return True
        except Exception:
            return False

    def setup_drop_area(app):
        try:
            p=app.tabs.get('offers')
            if p is None or getattr(app,'_offer_drop_area_ready',False):return
            app._offer_drop_area_ready=True
            children=p.winfo_children()
            box=M.ttk.Frame(p,style='Card.TFrame',padding=(16,12))
            box.pack(fill='x',before=children[0] if children else None,pady=(0,8))
            left=M.ttk.Frame(box,style='Card.TFrame');left.pack(side='left',fill='x',expand=True)
            M.ttk.Label(left,text='⇩  Přetáhněte sem nabídku nebo e-mail z Outlooku',style='Section.TLabel').pack(anchor='w')
            state=M.tk.StringVar(value='PDF / MSG • přímé přetažení z Outlooku • stejný parser a databáze')
            M.ttk.Label(left,textvariable=state,style='PageSubtitle.TLabel').pack(anchor='w',pady=(3,0))
            M.ttk.Button(box,text='Načíst vybraný e-mail z Outlooku',style='Toolbar.TButton',command=lambda:_import_outlook_selection(app,box)).pack(side='right',padx=(12,0))
            ok=_register_drop(app,box)
            # Register the whole offers page too, so user needn't hit the exact box.
            if ok:
                try:_register_drop(app,p)
                except Exception:pass
                state.set('PDF / MSG • přetažení z Průzkumníka i přímo z Outlooku')
            else:
                state.set('Drag & drop není dostupný – použijte tlačítko pro vybraný e-mail z Outlooku.')
        except Exception:
            pass

    old_init=M.App.__init__
    def init(self,*a,**k):
        old_init(self,*a,**k)
        try:self.after_idle(lambda:setup_drop_area(self))
        except Exception:pass
    M.App.__init__=init
    M.App.import_selected_outlook_offer=lambda self:_import_outlook_selection(self,self)

    # Help note for this release.
    try:
        old_help=M.App.build_help
        def help_page(self):
            r=old_help(self)
            try:
                import tkinter as tk
                p=self.tabs['help']
                def walk(w):
                    if isinstance(w,tk.Text):
                        w.configure(state='normal')
                        w.insert('end','\n\nNABÍDKY 6.0.20 – OUTLOOK DRAG & DROP\nV záložce Nabídky je oblast pro přetažení PDF/MSG. Ve Windows lze přetáhnout i vybraný e-mail přímo z otevřeného Outlooku. Pokud Outlook neposkytne běžnou cestu k souboru, CRM převezme aktuálně vybranou zprávu přes Outlook COM, dočasně ji uloží jako MSG a zpracuje stejným importním jádrem. Celý zdrojový MSG se ukládá do databáze pro budoucí opětovné zpracování. Jako záložní cesta je vedle drop zóny tlačítko „Načíst vybraný e-mail z Outlooku“.')
                        w.configure(state='disabled')
                    for c in w.winfo_children():walk(c)
                walk(p)
            except Exception:pass
            return r
        M.App.build_help=help_page
    except Exception:pass
