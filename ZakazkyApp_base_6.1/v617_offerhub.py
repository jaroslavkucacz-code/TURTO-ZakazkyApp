# TURTO CRM 6.0.17 - Offer Hub integration + autocomplete hard fix
import os, re, io, json, hashlib, tempfile, shutil, datetime
from pathlib import Path

def apply(M):
    # ------------------------------------------------------------------
    # 1) AUTOCOMPLETE: fix the base class directly, no more stacked focus hacks.
    # Popup is subordinate to CRM, never globally topmost. Enter commits the
    # highlighted/only result; arrows navigate; second Enter may reach dialog OK.
    # ------------------------------------------------------------------
    try:
        A=M.AutocompleteEntry
        old_show=A._show
        def show(self):
            r=old_show(self)
            try:
                if self.popup and self.popup.winfo_exists():
                    self.popup.attributes('-topmost',False)
                    self.popup.transient(self.winfo_toplevel())
                    if self.listbox and self.listbox.size():
                        self.listbox.selection_clear(0,'end');self.listbox.selection_set(0);self.listbox.activate(0);self.listbox.see(0)
            except:pass
            return r
        def navigate(self,delta):
            try:
                self._show()
                if not self.listbox or not self.listbox.size():return 'break'
                sel=self.listbox.curselection();cur=sel[0] if sel else 0
                nxt=max(0,min(self.listbox.size()-1,cur+delta))
                self.listbox.selection_clear(0,'end');self.listbox.selection_set(nxt);self.listbox.activate(nxt);self.listbox.see(nxt)
                # typing focus stays in entry
                self.focus_set();return 'break'
            except:return 'break'
        def accept(self,e=None):
            try:
                # committed value + hidden popup = allow second Enter to save dialog
                visible=bool(self.popup and self.popup.winfo_exists() and self.popup.winfo_viewable())
                if not visible and self.selected_value and (self.var.get() or '').strip()==str(self.selected_value).strip():
                    return None
                if not visible:self._show()
                if self.listbox and self.listbox.size():
                    sel=self.listbox.curselection();idx=sel[0] if sel else 0
                    self._set(self.listbox.get(idx));return 'break'
                return None
            except:return 'break'
        A._show=show;A._navigate=navigate;A._accept_first=accept
        prev_init=A.__init__
        def init(self,*a,**k):
            prev_init(self,*a,**k)
            self.bind('<Down>',lambda e:self._navigate(1));self.bind('<Up>',lambda e:self._navigate(-1))
            self.bind('<Return>',self._accept_first);self.bind('<KP_Enter>',self._accept_first)
            try:
                top=self.winfo_toplevel()
                top.bind('<FocusOut>',lambda e:self.hide(),add='+')
            except:pass
        A.__init__=init
    except:pass

    # ------------------------------------------------------------------
    # 2) OFFER SOURCE DATABASE. Original files/messages are preserved so a
    # parser can be improved later and old offers can be reprocessed.
    # ------------------------------------------------------------------
    try:
        with M.db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS offer_source_messages(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              source_path TEXT DEFAULT '', source_hash TEXT NOT NULL UNIQUE,
              subject TEXT DEFAULT '', sender TEXT DEFAULT '', sent_at TEXT DEFAULT '',
              body TEXT DEFAULT '', imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
              imported_by TEXT DEFAULT '', status TEXT DEFAULT '', note TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS offer_source_attachments(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              message_id INTEGER, filename TEXT NOT NULL, extension TEXT DEFAULT '',
              content_hash TEXT NOT NULL, content_blob BLOB,
              parser_supplier TEXT DEFAULT '', offer_id INTEGER,
              imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(message_id,content_hash),
              FOREIGN KEY(message_id) REFERENCES offer_source_messages(id) ON DELETE CASCADE,
              FOREIGN KEY(offer_id) REFERENCES supplier_offers(id)
            );
            CREATE INDEX IF NOT EXISTS idx_offer_source_att_hash ON offer_source_attachments(content_hash);
            CREATE INDEX IF NOT EXISTS idx_offer_source_msg_date ON offer_source_messages(sent_at DESC);
            CREATE TABLE IF NOT EXISTS offer_supplier_parsers(
              supplier_code TEXT PRIMARY KEY, display_name TEXT NOT NULL,
              enabled INTEGER NOT NULL DEFAULT 1, extensions TEXT DEFAULT '.pdf',
              supports_images INTEGER NOT NULL DEFAULT 0, module_name TEXT DEFAULT '', note TEXT DEFAULT ''
            );
            INSERT OR IGNORE INTO offer_supplier_parsers(supplier_code,display_name,enabled,extensions,supports_images,module_name,note)
              VALUES('GEROTOP','GEROtop',1,'.pdf',1,'Gerotop_Nabidky','Parser převzatý z původního TURTO programu');
            INSERT OR IGNORE INTO offer_supplier_parsers(supplier_code,display_name,enabled,extensions,supports_images,module_name,note)
              VALUES('LEVIAT','Leviat',1,'.pdf',0,'Leviat_Nabidky','Parser převzatý z původního TURTO programu');
            ''')
    except:pass

    def _msg_date(v):
        if not v:return ''
        try:
            if hasattr(v,'strftime'):return v.strftime('%Y-%m-%d %H:%M:%S')
        except:pass
        return str(v)

    def _attachment_bytes(att):
        data=getattr(att,'data',None)
        if callable(data):data=data()
        if data is None:
            try:data=att.get_data()
            except:pass
        if isinstance(data,str):return data.encode('utf-8',errors='replace')
        return bytes(data or b'')

    def process_pdf(app,path,source_message_id=None,attachment_name=None,attachment_bytes=None):
        path=Path(path)
        oid,created,count,parsed=M.save_offer_import(path)
        supplier=str(parsed.get('supplier') or '')
        if source_message_id and attachment_bytes is not None:
            h=hashlib.sha256(attachment_bytes).hexdigest()
            with M.db() as c:
                c.execute('''INSERT OR IGNORE INTO offer_source_attachments
                    (message_id,filename,extension,content_hash,content_blob,parser_supplier,offer_id)
                    VALUES(?,?,?,?,?,?,?)''',(source_message_id,attachment_name or path.name,path.suffix.lower(),h,M.sqlite3.Binary(attachment_bytes),supplier,oid))
                c.execute('UPDATE offer_source_attachments SET offer_id=?,parser_supplier=? WHERE message_id=? AND content_hash=?',(oid,supplier,source_message_id,h))
        return {'offer_id':oid,'created':created,'items':count,'supplier':supplier,'number':parsed.get('offer_no',''),'reference':parsed.get('reference','')}

    def process_msg(app,path):
        path=Path(path);raw=path.read_bytes();mh=hashlib.sha256(raw).hexdigest()
        try:
            import extract_msg
        except Exception as e:
            raise RuntimeError('Pro import .MSG chybí knihovna extract-msg. Spusťte instalaci knihoven / aktualizaci balíčku.') from e
        msg=extract_msg.Message(str(path))
        subject=str(getattr(msg,'subject','') or '');sender=str(getattr(msg,'sender','') or getattr(msg,'senderEmail','') or '')
        sent=_msg_date(getattr(msg,'date',''));body=str(getattr(msg,'body','') or '')
        with M.db() as c:
            row=c.execute('SELECT id FROM offer_source_messages WHERE source_hash=?',(mh,)).fetchone()
            if row:mid=row['id']
            else:mid=c.execute('''INSERT INTO offer_source_messages(source_path,source_hash,subject,sender,sent_at,body,imported_by,status)
                VALUES(?,?,?,?,?,?,?,?)''',(str(path),mh,subject,sender,sent,body,M.get_setting('active_user',''),'ZPRACOVÁVÁ SE')).lastrowid
        results=[];attachments=0;unsupported=[]
        with tempfile.TemporaryDirectory(prefix='turto_msg_') as td:
            td=Path(td)
            for n,att in enumerate(getattr(msg,'attachments',[]) or [],1):
                name=str(getattr(att,'longFilename',None) or getattr(att,'shortFilename',None) or getattr(att,'name',None) or f'priloha_{n}')
                data=_attachment_bytes(att)
                if not data:continue
                attachments+=1;ext=Path(name).suffix.lower();h=hashlib.sha256(data).hexdigest()
                with M.db() as c:
                    c.execute('''INSERT OR IGNORE INTO offer_source_attachments(message_id,filename,extension,content_hash,content_blob)
                                 VALUES(?,?,?,?,?)''',(mid,name,ext,h,M.sqlite3.Binary(data)))
                safe=re.sub(r'[^\w.()\- ]+','_',Path(name).name);tmp=td/safe;tmp.write_bytes(data)
                if ext=='.pdf':
                    try:results.append(process_pdf(app,tmp,mid,name,data))
                    except Exception as e:results.append({'error':f'{name}: {e}'})
                elif ext in ('.msg',):
                    # nested MSG is preserved now; recursive mail parsing can be enabled later without data loss
                    unsupported.append(name)
                elif ext in ('.xlsx','.xls','.xlsm'):
                    # preserve Excel attachments for supplier plugins; do not silently invent parsing rules
                    unsupported.append(name)
                else:unsupported.append(name)
        try:msg.close()
        except:pass
        good=[r for r in results if not r.get('error')]
        with M.db() as c:c.execute('UPDATE offer_source_messages SET status=?,note=? WHERE id=?',('HOTOVO' if good else 'BEZ ROZPOZNANÉ PDF NABÍDKY',f'Příloh: {attachments}; rozpoznaných nabídek: {len(good)}; ostatní: {len(unsupported)}',mid))
        return {'message_id':mid,'attachments':attachments,'offers':good,'results':results,'unsupported':unsupported,'subject':subject}

    def import_offer_sources(app):
        from tkinter import filedialog,messagebox
        paths=filedialog.askopenfilenames(parent=app,title='Importovat cenové nabídky',filetypes=[('Nabídky / e-maily','*.pdf *.msg'),('PDF','*.pdf'),('Outlook zprávy','*.msg'),('Všechny soubory','*.*')])
        if not paths:return
        ok=[];errors=[];msg_count=0;att_count=0
        for p in paths:
            try:
                if str(p).lower().endswith('.msg'):
                    r=process_msg(app,p);msg_count+=1;att_count+=r['attachments'];ok.extend(r['offers'])
                    for x in r['results']:
                        if x.get('error'):errors.append(x['error'])
                elif str(p).lower().endswith('.pdf'):ok.append(process_pdf(app,p))
                else:errors.append(f'{Path(p).name}: nepodporovaný vstupní formát')
            except Exception as e:errors.append(f'{Path(p).name}: {e}')
        try:app.refresh_offers()
        except:pass
        suppliers={x.get('supplier','') for x in ok if x.get('supplier')}
        text=f'Import dokončen.\n\nNabídky: {len(ok)}\nMSG: {msg_count}\nPřílohy v MSG: {att_count}'
        if suppliers:text+='\nDodavatelé: '+', '.join(sorted(suppliers))
        if errors:text+=f'\n\nChyby / nerozpoznané: {len(errors)}\n'+'\n'.join(errors[:12])
        messagebox.showinfo('Zpracování cenových nabídek',text,parent=app)
    M.App.import_offer_sources=import_offer_sources
    M.process_offer_msg=process_msg;M.process_offer_pdf=process_pdf

    # ------------------------------------------------------------------
    # 3) Offers UI: add unified PDF/MSG entry point without removing old PDF
    # import. Existing history, item images, aliases, action linking and search
    # stay intact.
    # ------------------------------------------------------------------
    old_build=M.App.build_offers
    def build_offers(self):
        old_build(self)
        try:
            p=self.tabs['offers'];children=p.winfo_children()
            tools=M.ttk.Frame(p,style='Panel.TFrame',padding=(10,7));tools.pack(fill='x',before=children[0] if children else None,pady=(0,5))
            M.ttk.Button(tools,text='📥 Zpracovat PDF / MSG',style='Accent.TButton',command=self.import_offer_sources).pack(side='left')
            M.ttk.Label(tools,text='Leviat + GEROtop • ukládání do databáze • historie cen • obrázky • připraveno pro další dodavatele',style='PageSubtitle.TLabel').pack(side='left',padx=10)
        except:pass
    M.App.build_offers=build_offers

    # ------------------------------------------------------------------
    # 4) Help: append Offer Hub process description.
    # ------------------------------------------------------------------
    old_help=M.App.build_help
    def help_page(self):
        r=old_help(self)
        try:
            import tkinter as tk
            p=self.tabs['help']
            def walk(w):
                if isinstance(w,tk.Text):
                    w.configure(state='normal');w.insert('end','\n\nNABÍDKY – ZPRACOVÁNÍ PDF / MSG\nV záložce Nabídky lze zpracovat přímo PDF nebo Outlook .MSG. CRM uchová metadata zprávy i přílohy pro pozdější opětovné zpracování. PDF nabídky Leviat a GEROtop jsou rozpoznány automaticky, položky, ceny, slevy a dostupné obrázky se ukládají do databáze a vstupují do historie cen. Import stejného PDF je chráněn hashem proti duplicitě. Architektura parserů je oddělená podle dodavatele, aby bylo možné postupně přidávat další formáty bez přepisování databáze a Nabídek. Excelové a jiné přílohy z MSG se zatím bezpečně uchovají; parser se k nim může doplnit pro konkrétního dodavatele.')
                    w.configure(state='disabled')
                for c in w.winfo_children():walk(c)
            walk(p)
        except:pass
        return r
    M.App.build_help=help_page
