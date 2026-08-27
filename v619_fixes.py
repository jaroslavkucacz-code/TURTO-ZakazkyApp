# TURTO CRM 6.0.19 - robust MSG import + inline product image panel
import io, hashlib, tempfile, re
from pathlib import Path

def apply(M):
    # ------------------------------------------------------------------
    # 1) Robust Outlook .MSG import. Use extract_msg.openMsg and tolerate
    # attachment API differences across extract-msg versions.
    # ------------------------------------------------------------------
    def _bytes_from_attachment(att, tempdir):
        # Common case: .data is already bytes.
        try:
            data=getattr(att,'data',None)
            if callable(data):data=data()
            if isinstance(data,(bytes,bytearray,memoryview)):return bytes(data)
        except Exception:pass
        # Some versions expose get_data().
        try:
            data=att.get_data()
            if isinstance(data,(bytes,bytearray,memoryview)):return bytes(data)
        except Exception:pass
        # Last safe fallback: let extract-msg save the attachment and read it back.
        try:
            before={p.name for p in Path(tempdir).iterdir()}
            result=att.save(customPath=str(tempdir))
            candidates=[]
            if result:
                try:candidates.append(Path(result))
                except Exception:pass
            after=[p for p in Path(tempdir).iterdir() if p.name not in before and p.is_file()]
            candidates+=after
            for p in candidates:
                if p.exists() and p.is_file():return p.read_bytes()
        except Exception:pass
        return b''

    def process_msg(app,path):
        path=Path(path);raw=path.read_bytes();mh=hashlib.sha256(raw).hexdigest()
        try:
            import extract_msg
        except Exception as e:
            raise RuntimeError('Knihovna extract-msg není dostupná. Aktualizujte/obnovte knihovny aplikace.') from e
        try:
            msg=extract_msg.openMsg(str(path))
        except Exception as e:
            raise RuntimeError(f'.MSG se nepodařilo otevřít: {e}') from e
        try:
            subject=str(getattr(msg,'subject','') or '')
            sender=str(getattr(msg,'sender','') or getattr(msg,'senderEmail','') or '')
            sent=getattr(msg,'date','')
            try:sent=sent.strftime('%Y-%m-%d %H:%M:%S') if hasattr(sent,'strftime') else str(sent or '')
            except Exception:sent=str(sent or '')
            body=str(getattr(msg,'body','') or '')
            with M.db() as c:
                row=c.execute('SELECT id FROM offer_source_messages WHERE source_hash=?',(mh,)).fetchone()
                if row:mid=row['id']
                else:mid=c.execute('''INSERT INTO offer_source_messages(source_path,source_hash,subject,sender,sent_at,body,imported_by,status)
                    VALUES(?,?,?,?,?,?,?,?)''',(str(path),mh,subject,sender,sent,body,M.get_setting('active_user',''),'ZPRACOVÁVÁ SE')).lastrowid
            results=[];attachments=0;unsupported=[];errors=[]
            with tempfile.TemporaryDirectory(prefix='turto_msg_') as td:
                tdp=Path(td)
                for n,att in enumerate(getattr(msg,'attachments',[]) or [],1):
                    name=str(getattr(att,'longFilename',None) or getattr(att,'shortFilename',None) or getattr(att,'name',None) or f'priloha_{n}')
                    data=_bytes_from_attachment(att,tdp)
                    if not data:
                        errors.append(f'{name}: přílohu se nepodařilo načíst')
                        continue
                    attachments+=1;ext=Path(name).suffix.lower();h=hashlib.sha256(data).hexdigest()
                    with M.db() as c:
                        c.execute('''INSERT OR IGNORE INTO offer_source_attachments(message_id,filename,extension,content_hash,content_blob)
                                     VALUES(?,?,?,?,?)''',(mid,name,ext,h,M.sqlite3.Binary(data)))
                    safe=re.sub(r'[^\w.()\- ]+','_',Path(name).name) or f'priloha_{n}'
                    tmp=tdp/(f'{n:03d}_'+safe);tmp.write_bytes(data)
                    if ext=='.pdf':
                        try:
                            r=M.process_offer_pdf(app,tmp,mid,name,data);results.append(r)
                        except Exception as e:errors.append(f'{name}: {e}')
                    else:unsupported.append(name)
            good=[r for r in results if r and not r.get('error')]
            note=f'Příloh: {attachments}; rozpoznaných nabídek: {len(good)}; ostatní: {len(unsupported)}; chyb: {len(errors)}'
            with M.db() as c:c.execute('UPDATE offer_source_messages SET status=?,note=? WHERE id=?',('HOTOVO' if good else ('NAČTENO – BEZ ROZPOZNANÉ PDF NABÍDKY' if attachments else 'BEZ PŘÍLOH'),note,mid))
            return {'message_id':mid,'attachments':attachments,'offers':good,'results':results,'unsupported':unsupported,'errors':errors,'subject':subject}
        finally:
            try:msg.close()
            except Exception:pass
    M.process_offer_msg=process_msg

    # Replace import entry point so detailed MSG errors are actually reported.
    def import_offer_sources(app):
        from tkinter import filedialog,messagebox
        paths=filedialog.askopenfilenames(parent=app,title='Importovat cenové nabídky',filetypes=[('Nabídky / e-maily','*.pdf *.msg'),('PDF','*.pdf'),('Outlook zprávy','*.msg'),('Všechny soubory','*.*')])
        if not paths:return
        ok=[];errors=[];msg_count=0;att_count=0
        for p in paths:
            try:
                if str(p).lower().endswith('.msg'):
                    r=process_msg(app,p);msg_count+=1;att_count+=r['attachments'];ok.extend(r['offers']);errors.extend(r.get('errors') or [])
                elif str(p).lower().endswith('.pdf'):
                    ok.append(M.process_offer_pdf(app,p))
                else:errors.append(f'{Path(p).name}: nepodporovaný vstupní formát')
            except Exception as e:errors.append(f'{Path(p).name}: {e}')
        try:app.refresh_offers()
        except Exception:pass
        text=f'Import dokončen.\n\nNabídky: {len(ok)}\nMSG: {msg_count}\nPřílohy v MSG: {att_count}'
        if errors:text+='\n\nChyby:\n'+'\n'.join(errors[:15])
        messagebox.showinfo('Zpracování cenových nabídek',text,parent=app)
    M.App.import_offer_sources=import_offer_sources

    # ------------------------------------------------------------------
    # 2) GEROtop/product images directly inside the Offer detail window.
    # No second Toplevel. Selecting a row refreshes preview + product data.
    # ------------------------------------------------------------------
    try:
        import crm_features as F
        D=F.OfferDetailDialog
        old_build=D._build
        def _load_image_for(self,it):
            if not it:return None
            supplier=self.offer_row['supplier'] or self.offer_row['supplier_name'] or ''
            with M.db() as con:
                im=con.execute('SELECT image_blob,image_ext,source_offer_no,source_offer_date FROM offer_product_images WHERE supplier=? AND item_key=?',(supplier,it['item_key'])).fetchone()
                if not im or not im['image_blob']:
                    im2=con.execute('SELECT image_blob,image_ext FROM supplier_offer_items WHERE id=?',(it['id'],)).fetchone()
                    if im2 and im2['image_blob']:
                        return {'image_blob':im2['image_blob'],'image_ext':im2['image_ext'],'source_offer_no':self.offer_row['offer_number'],'source_offer_date':self.offer_row['offer_date']}
            return dict(im) if im and im['image_blob'] else None
        def refresh_preview(self,*_):
            try:
                it=self._selected_item()
                if not it:return
                self.preview_title.configure(text=it.get('original_name') or it.get('item_key') or 'Položka')
                self.preview_meta.configure(text=f"Kód: {it.get('product_code') or '—'}   •   Množství: {it.get('quantity') or 0} {it.get('unit') or ''}   •   Cena/ks: {float(it.get('unit_price') or 0):,.2f}")
                im=_load_image_for(self,it)
                if not im:
                    self.preview_image.configure(image='',text='K této položce není uložen obrázek.');self.preview_image.image=None
                    self.preview_source.configure(text='');return
                from PIL import Image,ImageTk
                img=Image.open(io.BytesIO(bytes(im['image_blob'])));img.thumbnail((320,220));ph=ImageTk.PhotoImage(img)
                self.preview_image.configure(image=ph,text='');self.preview_image.image=ph
                self.preview_source.configure(text=f"Zdroj obrázku: nabídka {im.get('source_offer_no') or '—'} z {M.fmt_date(im.get('source_offer_date'))}")
            except Exception as e:
                try:self.preview_image.configure(image='',text=f'Obrázek nelze zobrazit: {e}')
                except Exception:pass
        def build(self):
            old_build(self)
            try:
                # Remove the old separate-window image button if present by simply changing its semantics.
                # Add a permanent preview panel into the same detail window.
                panel=M.ttk.Frame(self.f,style='Card.TFrame',padding=12)
                panel.pack(fill='x',pady=(8,0))
                self.preview_title=M.ttk.Label(panel,text='Vyberte položku',style='Section.TLabel');self.preview_title.grid(row=0,column=0,sticky='w')
                self.preview_meta=M.ttk.Label(panel,text='',style='PageSubtitle.TLabel');self.preview_meta.grid(row=1,column=0,sticky='w',pady=(2,8))
                self.preview_image=M.ttk.Label(panel,text='Vyberte položku nabídky.');self.preview_image.grid(row=0,column=1,rowspan=3,sticky='e',padx=(18,0))
                self.preview_source=M.ttk.Label(panel,text='',style='PageSubtitle.TLabel');self.preview_source.grid(row=2,column=0,sticky='w')
                panel.columnconfigure(0,weight=1)
                self.tree.bind('<<TreeviewSelect>>',lambda e:refresh_preview(self),add='+')
                if self.tree.get_children():
                    first=self.tree.get_children()[0];self.tree.selection_set(first);self.tree.focus(first);refresh_preview(self)
            except Exception:pass
        def open_image_inline(self):
            refresh_preview(self)
            try:self.preview_image.focus_set()
            except Exception:pass
        D._build=build;D.open_image=open_image_inline;D.refresh_preview=refresh_preview
    except Exception:pass

    # Help note
    try:
        old_help=M.App.build_help
        def help_page(self):
            r=old_help(self)
            try:
                import tkinter as tk
                p=self.tabs['help']
                def walk(w):
                    if isinstance(w,tk.Text):
                        w.configure(state='normal');w.insert('end','\n\nNABÍDKY 6.0.19\nImport Outlook .MSG je odolnější vůči různým verzím extract-msg a načítání příloh. Při chybě se vypíše konkrétní problematická příloha. Obrázky položek GEROtop se zobrazují přímo v detailu nabídky spolu s údaji vybrané položky; neotevírá se samostatné okno.');w.configure(state='disabled')
                    for c in w.winfo_children():walk(c)
                walk(p)
            except Exception:pass
            return r
        M.App.build_help=help_page
    except Exception:pass
