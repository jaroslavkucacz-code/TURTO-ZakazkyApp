# TURTO CRM 6.0.25 - nonmodal updates, smooth resize, Outlook selection import hardening
import os, tempfile, urllib.request, json, datetime
from pathlib import Path


def apply(M):
    # ------------------------------------------------------------------
    # 1) Live updates: NEVER block the application with grab_set().
    # Replace crm_runtime live checker before App is instantiated.
    # ------------------------------------------------------------------
    try:
        import crm_runtime as R

        def _ver(v):
            try:return tuple(int(x) for x in str(v).split('.'))
            except:return (0,)

        def live_update_checks(app):
            state={'version':'','checking':False}

            def show_notice(version,notes):
                # Single non-modal notice. No grab_set, no wait_window.
                try:
                    old=getattr(app,'_update_notice_window',None)
                    if old is not None and old.winfo_exists():
                        try:old.destroy()
                        except Exception:pass
                except Exception:pass
                try:
                    d=M.tk.Toplevel(app);app._update_notice_window=d
                    d.title(f'Aktualizace {version}')
                    d.transient(app)
                    try:M.enable_dialog_maximize(d,680,420)
                    except Exception:pass
                    f=M.ttk.Frame(d,padding=18);f.pack(fill='both',expand=True)
                    M.ttk.Label(f,text=f'Je dostupná nová verze {version}',style='Section.TLabel').pack(anchor='w')
                    M.ttk.Label(f,text='Co aktualizace obsahuje:',style='PageSubtitle.TLabel').pack(anchor='w',pady=(12,4))
                    txt=M.tk.Text(f,height=9,wrap='word',font=('Calibri',11));txt.pack(fill='both',expand=True)
                    txt.insert('1.0',notes);txt.configure(state='disabled')
                    bar=M.ttk.Frame(f);bar.pack(fill='x',pady=(12,0))
                    M.ttk.Button(bar,text='Později',command=d.destroy).pack(side='right')
                    M.ttk.Button(bar,text='Aktualizovat',style='Accent.TButton',command=lambda:(d.destroy(),app.check_for_updates(silent=False))).pack(side='right',padx=6)
                    # Never own a modal grab. If an older orphan grab exists, release it.
                    try:
                        g=app.grab_current()
                        if g is d:g.grab_release()
                    except Exception:pass
                    try:d.lift()
                    except Exception:pass
                except Exception:pass

            def check_worker():
                if state['checking']:return
                state['checking']=True
                try:
                    if str(M.get_setting('company_auto_updates','1'))=='0':return
                    req=urllib.request.Request(
                        R.GITHUB_UPDATE+'/latest.json?ts='+str(int(datetime.datetime.now().timestamp())),
                        headers={'User-Agent':'TURTO-CRM'})
                    with urllib.request.urlopen(req,timeout=8) as resp:data=json.load(resp)
                    nv=str(data.get('version','')).strip();cur=str(M.APP_VERSION)
                    if nv and _ver(nv)>_ver(cur) and state['version']!=nv:
                        state['version']=nv
                        notes=str(data.get('notes','')).strip() or 'Drobné opravy a vylepšení.'
                        app.after(0,lambda v=nv,n=notes:show_notice(v,n))
                except Exception:pass
                finally:
                    state['checking']=False

            def schedule():
                try:
                    import threading
                    threading.Thread(target=check_worker,daemon=True).start()
                except Exception:check_worker()
                try:app.after(10*60*1000,schedule)
                except Exception:pass

            app.after(1200,schedule)

        R._live_update_checks=live_update_checks
    except Exception:pass

    # ------------------------------------------------------------------
    # 2) Outlook button: save selected MailItem as Unicode MSG, then feed the
    # exact same process_offer_msg() used for a normal MSG from disk.
    # ------------------------------------------------------------------
    def import_selected_outlook(app,parent=None):
        from tkinter import messagebox
        if os.name!='nt':
            return messagebox.showerror('Přenos z Outlooku','Přímý import z Outlooku je dostupný pouze ve Windows.',parent=parent or app)
        try:
            import win32com.client
        except Exception as e:
            return messagebox.showerror('Přenos z Outlooku','Chybí pywin32. Restartujte aplikaci po aktualizaci.\n\n'+str(e),parent=parent or app)
        td=None
        try:
            try:ol=win32com.client.GetActiveObject('Outlook.Application')
            except Exception:ol=win32com.client.Dispatch('Outlook.Application')
            explorer=ol.ActiveExplorer();sel=explorer.Selection if explorer is not None else None
            count=int(sel.Count) if sel is not None else 0
            if count<1:raise RuntimeError('V Outlooku není vybraný žádný e-mail.')
            td=tempfile.TemporaryDirectory(prefix='turto_outlook_')
            paths=[]
            for i in range(1,count+1):
                item=sel.Item(i)
                try:
                    if int(getattr(item,'Class',0))!=43:continue
                except Exception:pass
                subject=str(getattr(item,'Subject','') or f'outlook_{i}')
                safe=''.join('_' if c in '<>:"/\\|?*' or ord(c)<32 else c for c in subject).strip(' ._')[:120] or f'outlook_{i}'
                p=Path(td.name)/(safe+'.msg')
                # 9 = olMSGUnicode. This avoids ANSI/codepage ambiguity and UTF-8 decode failures.
                try:item.SaveAs(str(p),9)
                except Exception:item.SaveAs(str(p),3)
                if p.exists() and p.stat().st_size>0:paths.append(p)
            if not paths:raise RuntimeError('Výběr Outlooku neobsahuje zpracovatelný e-mail.')

            good=[];errors=[]
            for p in paths:
                try:
                    r=M.process_offer_msg(app,p)
                    good.extend((r or {}).get('offers') or [])
                    for x in (r or {}).get('results') or []:
                        if isinstance(x,dict) and x.get('error'):errors.append(str(x['error']))
                except Exception as e:errors.append(f'{p.name}: {e}')
            try:app.refresh_offers()
            except Exception:pass
            if errors:
                title='Import se nezdařil' if not good else 'Import dokončen s chybami'
                return messagebox.showwarning(title,f'Nabídky: {len(good)}\n\n'+'\n'.join(errors[:12]),parent=parent or app)
            messagebox.showinfo('Přenos z Outlooku',f'Import dokončen. Nabídky: {len(good)}',parent=parent or app)
            return good
        except Exception as e:
            messagebox.showerror('Přenos z Outlooku',str(e),parent=parent or app);return []
        finally:
            try:
                if td:td.cleanup()
            except Exception:pass

    M.App.import_selected_outlook_offer=lambda self:import_selected_outlook(self,self)

    # ------------------------------------------------------------------
    # 3) Resize performance. Remove data-refresh callbacks from Treeview
    # <Configure>; keep only cheap geometry redraws, debounced.
    # ------------------------------------------------------------------
    def optimize_tree_configures(app):
        try:
            trees=[]
            def walk(w):
                try:
                    if isinstance(w,M.ttk.Treeview):trees.append(w)
                    for c in w.winfo_children():walk(c)
                except Exception:pass
            walk(app)
            for tree in trees:
                try:
                    tree.unbind('<Configure>')
                    state={'after':None}
                    def on_cfg(e,t=tree,s=state):
                        try:
                            if s['after'] is not None:t.after_cancel(s['after'])
                        except Exception:pass
                        def finish():
                            s['after']=None
                            try:
                                fn=getattr(t,'_sync_filter_bar',None)
                                if callable(fn):fn()
                            except Exception:pass
                            try:
                                fn=getattr(t,'_date_cell_redraw',None)
                                if callable(fn):fn()
                            except Exception:pass
                        try:s['after']=t.after(180,finish)
                        except Exception:pass
                    tree.bind('<Configure>',on_cfg,add='+')
                except Exception:pass
        except Exception:pass

    # ------------------------------------------------------------------
    # 4) Modal safety: a hidden/orphan grab must never make the main window
    # inaccessible. Releasing only invalid/non-viewable grabs preserves normal
    # visible dialogs.
    # ------------------------------------------------------------------
    def modal_safety(app):
        try:
            g=app.grab_current()
            if g is not None:
                invalid=False
                try:invalid=not bool(g.winfo_exists()) or not bool(g.winfo_viewable())
                except Exception:invalid=True
                if invalid:
                    try:g.grab_release()
                    except Exception:pass
        except Exception:pass
        try:app.after(1000,lambda:modal_safety(app))
        except Exception:pass

    # Patch the Outlook button created by v620 after full UI construction.
    def patch_outlook_button(app):
        try:
            def walk(w):
                for c in w.winfo_children():
                    try:
                        if c.winfo_class().endswith('Button') and 'Načíst vybraný e-mail z Outlooku' in str(c.cget('text')):
                            c.configure(command=lambda:import_selected_outlook(app,c.winfo_toplevel()))
                    except Exception:pass
                    walk(c)
            walk(app)
        except Exception:pass

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:self.after(500,lambda:optimize_tree_configures(self))
        except Exception:pass
        try:self.after(700,lambda:patch_outlook_button(self))
        except Exception:pass
        try:self.after(1000,lambda:modal_safety(self))
        except Exception:pass
        return r
    M.App.__init__=init

    # Help note.
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
                        w.insert('end','\n\nSTABILITA 6.0.25\nAutomatická kontrola aktualizací běží na pozadí a oznámení nové verze je neblokující; už nepoužívá modální grab. Změna velikosti hlavního okna nespouští databázové refreshe při každém pixelu a pomocné geometrické přepočty se provedou až po krátkém uklidnění resize. Tlačítko „Načíst vybraný e-mail z Outlooku“ ukládá vybranou zprávu jako Unicode MSG a předává ji stejnému process_msg() jako běžný soubor z disku. Skrytý nebo neplatný modální grab je automaticky uvolněn.')
                        w.configure(state='disabled')
                    for c in w.winfo_children():walk(c)
                walk(p)
            except Exception:pass
            return r
        M.App.build_help=help_page
    except Exception:pass
