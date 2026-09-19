"""Lazy map tab, canonical record dialogs, safe pin editing and local RÚIAN."""
from __future__ import annotations

from contextlib import closing
import queue
import sqlite3
import threading
import tkinter as tk
from tkinter import ttk, filedialog
import webbrowser
from urllib.parse import urlsplit

from . import model, ruian
from .bridge import Bridge
from ..platform import user_access as access, grouped_navigation as navigation


class Workspace:
    def __init__(self, M, app, page):
        self.M, self.app, self.page = M, app, page
        self.bridge = None
        self.records = {}
        self.pending_pick = None
        self.jobs = queue.Queue()
        self.job_running = False
        self.generation = 0
        self.loaded = False
        self.embedded = False
        self.last_applied_count = None
        self.layer = tk.StringVar(value='Obojí')
        self.phase = tk.StringVar(value='Všechny stavy')
        self.supplying = tk.BooleanVar(value=False)
        self.query = tk.StringVar()
        self.start_from, self.start_to = tk.StringVar(), tk.StringVar()
        self.company = tk.StringVar(value='Všechny společnosti')
        self.company_ids = {}
        self.gps = tk.StringVar()
        self.selected_label = tk.StringVar(value='Vyberte záznam v seznamu nebo na mapě.')
        self.status = tk.StringVar(value='Online podklad OpenFreeMap · GPS a údaje zůstávají v CRM.')
        self._refresh_after = None
        self._apply_after = None
        page.columnconfigure(0, weight=1); page.rowconfigure(2, weight=1)
        top = ttk.Frame(page, padding=(12, 8)); top.grid(row=0, column=0, sticky='ew')
        ttk.Label(top, text='Mapa', font=('Calibri', 18, 'bold')).pack(side='left', padx=(0, 15))
        for var, values, width in ((self.layer, ('Obojí', 'Společnosti', 'Akce'), 14),
                                    (self.phase, ('Všechny stavy', *model.PHASES), 18)):
            box = ttk.Combobox(top, textvariable=var, values=values, state='readonly', width=width)
            box.pack(side='left', padx=4); box.bind('<<ComboboxSelected>>', lambda e: self.refresh())
        ttk.Checkbutton(top, text='Dodáváme', variable=self.supplying, command=self.refresh).pack(side='left', padx=8)
        ttk.Button(top, text='Obnovit zobrazení', command=self.reload).pack(side='right')
        filters = ttk.Frame(page, padding=(12, 0, 12, 8)); filters.grid(row=1, column=0, sticky='ew')
        filters.columnconfigure(1, weight=1)
        ttk.Label(filters, text='Hledat').grid(row=0, column=0, sticky='w')
        entry = ttk.Entry(filters, textvariable=self.query, width=28); entry.grid(row=0, column=1, sticky='ew', padx=(6, 12))
        entry.bind('<Return>', lambda e: self.refresh())
        ttk.Label(filters, text='Zahájení Akce od').grid(row=0, column=2)
        M.DatePicker(filters, self.start_from).grid(row=0, column=3, padx=5)
        ttk.Label(filters, text='do').grid(row=0, column=4)
        M.DatePicker(filters, self.start_to).grid(row=0, column=5, padx=5)
        ttk.Button(filters, text='Filtrovat', command=self.refresh).grid(row=0, column=6, padx=5)
        ttk.Button(filters, text='Reset filtrů', command=self.reset).grid(row=0, column=7)
        self.company_box = ttk.Combobox(filters, textvariable=self.company, state='readonly', width=40)
        self.company_box.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(7,0), padx=(0,12))
        self.company_box.bind('<<ComboboxSelected>>', lambda e: self.refresh())
        ttk.Label(filters, text='Modrá: společnost · Zlatá: akce · Zelená: dodáváme · Šedá: ukončeno').grid(row=1, column=2, columnspan=6, sticky='w', pady=(7,0))
        panes = ttk.Panedwindow(page, orient='horizontal'); panes.grid(row=2, column=0, sticky='nsew', padx=12)
        left = ttk.Frame(panes, width=360); right = ttk.Frame(panes)
        panes.add(left, weight=1); panes.add(right, weight=3)
        left.columnconfigure(0, weight=1); left.rowconfigure(0, weight=3, minsize=105)
        left.rowconfigure(2, weight=2, minsize=75)
        self.tree = ttk.Treeview(left, columns=('name','state'), show='headings', selectmode='browse', height=5,
                                 name='layout__map__canonical_records')
        self.tree.heading('name', text='Záznam v CRM'); self.tree.column('name', width=240, minwidth=120)
        self.tree.heading('state', text='Poloha / stav'); self.tree.column('state', width=140, minwidth=100)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview); scroll.grid(row=0, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>', self.select)
        self.tree.bind('<Double-1>', lambda e: self.open_record())
        self.tree.bind('<Return>', lambda e: self.open_record())
        tools = ttk.Frame(left, padding=(0,8)); tools.grid(row=1, column=0, columnspan=2, sticky='ew')
        ttk.Button(tools, text='Otevřít záznam', command=self.open_record).pack(side='left')
        ttk.Button(tools, text='Zobrazit bod', command=self.focus).pack(side='left', padx=5)
        ttk.Button(tools, text='Zobrazit vše', command=lambda:self.send({'type':'fit'})).pack(side='left')
        details = ttk.Frame(left); details.grid(row=2,column=0,columnspan=2,sticky='nsew')
        details.columnconfigure(0,weight=1); details.rowconfigure(0,weight=1)
        self.details_canvas = tk.Canvas(details,height=165,highlightthickness=0,
                                       background=ttk.Style(page).lookup('TFrame','background') or '#edf2f4')
        self.details_canvas.grid(row=0,column=0,sticky='nsew')
        details_scroll = ttk.Scrollbar(details,orient='vertical',command=self.details_canvas.yview)
        details_scroll.grid(row=0,column=1,sticky='ns')
        self.details_canvas.configure(yscrollcommand=details_scroll.set)
        details_body = ttk.Frame(self.details_canvas); details_body.columnconfigure(0,weight=1)
        canvas_window = self.details_canvas.create_window((0,0),window=details_body,anchor='nw')
        details_body.bind('<Configure>',lambda e:self.details_canvas.configure(scrollregion=self.details_canvas.bbox('all')))
        self.details_canvas.bind('<Configure>',lambda e:self.details_canvas.itemconfigure(canvas_window,width=e.width))
        edit = ttk.LabelFrame(details_body, text='Poloha vybraného záznamu', padding=10)
        edit.grid(row=0, column=0, sticky='ew', pady=(0,8)); edit.columnconfigure(0, weight=1)
        ttk.Label(edit, textvariable=self.selected_label, wraplength=330).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0,6))
        self.gps_entry = ttk.Entry(edit, textvariable=self.gps); self.gps_entry.grid(row=1, column=0, columnspan=2, sticky='ew')
        ttk.Label(edit, text='GPS: šířka, délka (např. 49.1951, 16.6068)',wraplength=320).grid(row=2, column=0, columnspan=2, sticky='w', pady=3)
        self.save_button = ttk.Button(edit, text='Uložit GPS', command=self.save_gps); self.save_button.grid(row=3, column=0, sticky='ew', pady=3)
        self.pick_button = ttk.Button(edit, text='Umístit kliknutím', command=self.pick); self.pick_button.grid(row=3, column=1, padx=(5,0), pady=3)
        self.address_button = ttk.Button(edit, text='Dohledat adresu v ČR', command=self.lookup); self.address_button.grid(row=4, column=0, sticky='ew', pady=3)
        ttk.Button(edit, text='Zrušit umístění', command=self.cancel_pick).grid(row=4, column=1, padx=(5,0), pady=3)
        cache = ttk.Frame(details_body); cache.grid(row=1, column=0, sticky='ew')
        ttk.Button(cache, text='Stáhnout adresář ČR', command=self.download).grid(row=0, column=0, sticky='ew', padx=(0,5), pady=3)
        ttk.Button(cache, text='Importovat ZIP ČÚZK', command=self.import_zip).grid(row=0, column=1, sticky='ew', pady=3)
        ttk.Button(cache, text='Doplnit polohy podle adres', command=self.batch_lookup).grid(row=1, column=0, columnspan=2, sticky='ew', pady=3)
        ttk.Label(cache, text='Adresář se stahuje jednou. Vyhledávání adres pak probíhá v tomto počítači.',
                  wraplength=330).grid(row=2, column=0, columnspan=2, sticky='w', pady=5)
        self.map_frame = tk.Frame(right, background='#edf2f4'); self.map_frame.pack(fill='both', expand=True)
        self.placeholder = ttk.Label(self.map_frame, text='Mapa se načte při otevření záložky.', anchor='center', wraplength=420)
        self.placeholder.pack(fill='both', expand=True, padx=15, pady=15)
        footer = ttk.Frame(page, padding=(12,8)); footer.grid(row=3, column=0, sticky='ew')
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status, wraplength=800).grid(row=0, column=0, sticky='w')
        ttk.Button(footer, text='Zdroje mapy', command=lambda:webbrowser.open('https://openfreemap.org/')).grid(row=0, column=1, padx=5)
        self.runtime_button = ttk.Button(footer, text='Instalovat WebView2', command=lambda:webbrowser.open('https://developer.microsoft.com/microsoft-edge/webview2/'))
        self.runtime_button.grid(row=0,column=2); self.runtime_button.grid_remove()
        self.poll_after = None
        page.bind('<Destroy>', self.destroy, add='+')

    def destroy(self, event):
        if event.widget is not self.page: return
        self.generation += 1
        if self.bridge: self.bridge.close()
        for token in (self.poll_after, self._refresh_after, self._apply_after):
            if token:
                try: self.page.after_cancel(token)
                except tk.TclError: pass

    def send(self, data):
        if self.bridge: self.bridge.send(data)

    def activate(self):
        if not self.bridge:
            try:
                self.bridge = Bridge(self.map_frame, self.message)
                self.placeholder.pack_forget()
            except (RuntimeError, OSError) as exc:
                self.placeholder.configure(text=str(exc))
                self.runtime_button.grid()
        self.send({'type':'visible','value':True})
        self.refresh()

    def on_user_changed(self):
        self.generation += 1
        self.records.clear(); self.pending_pick = None
        # Destroy the old user's renderer, including queued pipe messages/popups.
        if self.bridge: self.bridge.close()
        self.bridge = None; self.loaded = False
        self.tree.delete(*self.tree.get_children())
        self.gps.set(''); self.selected_label.set('Vyberte záznam v seznamu nebo na mapě.')
        self.company.set('Všechny společnosti'); self.company_ids.clear()
        self.company_box.configure(values=('Všechny společnosti',))
        if getattr(self.app,'_current_page',None) == 'map' and access.level(self.M,'map') >= access.READ:
            self.activate()
        else: self.send({'type':'visible','value':False})

    def selected(self):
        selection = self.tree.selection()
        return self.records.get(selection[0]) if selection else None

    def select(self, event=None):
        self.cancel_pick()
        row = self.selected()
        self.gps.set(row['gps_coordinates'] or '' if row else '')
        self.selected_label.set(f"{row['title']}\n{row['address']}" if row else 'Vyberte záznam v seznamu nebo na mapě.')
        can_write = bool(row and access.level(self.M,'map') >= access.EDIT and access.level(self.M,model.TABLES[row['kind']]) >= access.EDIT)
        for control in (self.gps_entry, self.save_button, self.pick_button, self.address_button):
            control.configure(state='normal' if can_write else 'disabled')

    def refresh(self):
        try:
            access.require(self.M,'map',write=False)
            current = self.selected()
            selected_company = self.company_ids.get(self.company.get())
            with closing(self.M.db()) as con:
                choices = con.execute('SELECT id,official_name,short_name FROM companies WHERE active=1 AND merged_into_company_id IS NULL ORDER BY official_name').fetchall() if access.level(self.M,'companies') >= access.READ else []
            self.company_ids = {f"{r['official_name'] or r['short_name']} [ID {r['id']}]":r['id'] for r in choices}
            self.company_box.configure(values=('Všechny společnosti', *self.company_ids))
            selected_label = next((label for label,cid in self.company_ids.items() if cid == selected_company),'Všechny společnosti')
            self.company.set(selected_label)
            records = model.rows(self.M, layer={'Obojí':'both','Společnosti':'company','Akce':'project'}[self.layer.get()],
                phase='' if self.phase.get() == 'Všechny stavy' else self.phase.get(), supplying=self.supplying.get(),
                start_from=self.start_from.get(), start_to=self.start_to.get(), query=self.query.get(),
                company_id=self.company_ids.get(self.company.get()))
            self.records = {r['key']:r for r in records}
            self.tree.delete(*self.tree.get_children())
            for row in records:
                state = row['location_state'] if not row['coordinates'] else ('Společnost' if row['kind']=='company' else row['phase'] + (' · dodáváme' if row['supplying'] else ''))
                self.tree.insert('', 'end', iid=row['key'], values=(row['title'], state))
            if current and current['key'] in self.records:
                self.tree.selection_set(current['key'])
            self.select()
            self.send({'type':'data','data':model.features(records)})
            placed = sum(r['coordinates'] is not None for r in records)
            self.status.set(f'{len(records)} záznamů · {placed} bodů na mapě · {len(records)-placed} bez platné polohy. Filtry stavu a termínu platí pro Akce.')
        except (ValueError, sqlite3.Error) as exc:
            self.status.set(str(exc))
            if isinstance(exc, access.AccessDenied):
                self.records.clear(); self.tree.delete(*self.tree.get_children())
                self.send({'type':'data','data':model.features([])})

    def reload(self):
        self.send({'type':'reload'})
        if not self.bridge: self.activate()
        else: self.refresh()

    def reset(self):
        self.query.set(''); self.phase.set('Všechny stavy'); self.supplying.set(False)
        self.start_from.set(''); self.start_to.set(''); self.company.set('Všechny společnosti')
        self.refresh(); self.send({'type':'fit'})

    def message(self, event):
        kind = event.get('type')
        if kind == 'ready': self.refresh()
        elif kind == 'embedded': self.embedded = True
        elif kind == 'loaded': self.loaded = True
        elif kind == 'data-applied': self.last_applied_count = event.get('count')
        elif kind == 'attribution':
            url = str(event.get('url','')); parsed = urlsplit(url)
            if parsed.scheme == 'https' and parsed.hostname in {'openfreemap.org','openmaptiles.org','www.openstreetmap.org','maplibre.org'}:
                webbrowser.open(url)
        elif kind in ('select','open'):
            key = event.get('key')
            if key in self.records:
                self.tree.selection_set(key); self.tree.see(key)
                if kind == 'open': self.open_record()
        elif kind == 'picked' and self.pending_pick:
            row = self.pending_pick; self.pending_pick = None
            try:
                gps = f"{float(event['lat']):.7f}, {float(event['lon']):.7f}"
                model.point(self.M,gps)
                if self.M.messagebox.askyesno('Poloha', f"Uložit {gps} k záznamu „{row['title']}“?", parent=self.app):
                    model.save_location(self.M,row['kind'],row['id'],gps,model.snapshot(row))
                    self.app.refresh_all(); self.refresh()
            except (ValueError,KeyError,TypeError,sqlite3.Error) as exc: self.warn(exc)
        elif kind == 'error':
            self.status.set(str(event.get('message','Mapu se nepodařilo otevřít.')))
            if 'Runtime' in str(event.get('message','')): self.runtime_button.grid()
        elif kind == 'tile-error': self.status.set('Mapový podklad není dostupný. Data a seznam záznamů jsou dostupné; zkontrolujte připojení k internetu.')

    def warn(self, exc):
        self.M.messagebox.showwarning('Mapa',str(exc),parent=self.app)

    def focus(self):
        row = self.selected()
        if row: self.send({'type':'focus','key':row['key']})

    def open_record(self):
        row = self.selected()
        if not row: return
        try:
            model.record(self.M,row['kind'],row['id'])
            self.send({'type':'visible','value':False})
            dialog = self.M.CompanyDialog(self.app,row['id']) if row['kind']=='company' else self.M.ProjectDialog(self.app,row['id'])
            self.app.wait_window(dialog)
            if dialog.result: self.app.refresh_all()
        except (ValueError,sqlite3.Error) as exc: self.warn(exc)
        finally:
            self.send({'type':'visible','value':True}); self.refresh()

    def save_gps(self):
        row = self.selected()
        if not row: return
        try:
            model.save_location(self.M,row['kind'],row['id'],self.gps.get(),model.snapshot(row))
            self.app.refresh_all(); self.refresh()
        except (ValueError,sqlite3.Error) as exc: self.warn(exc)

    def pick(self):
        row = self.selected()
        if not row: return
        try:
            access.require(self.M,'map'); access.require(self.M,model.TABLES[row['kind']])
            if not self.loaded: raise ValueError('Nejdřív počkejte na načtení mapového podkladu nebo zadejte GPS ručně.')
            self.pending_pick = dict(row); self.send({'type':'pick','value':True})
        except ValueError as exc: self.warn(exc)

    def cancel_pick(self):
        self.pending_pick = None; self.send({'type':'pick','value':False})

    def lookup(self):
        row = self.selected()
        if not row: return
        try:
            matches = ruian.lookup(row['address'])
            if len(matches) != 1:
                raise ValueError('Adresa nemá jednoznačnou shodu v adresáři ČR. Zkontrolujte ulici, číslo domu, obec a PSČ; případně umístěte bod ručně.')
            match = matches[0]
            if not self.M.messagebox.askyesno('Adresa RÚIAN',f"{match['label']}\n\nUložit polohu k „{row['title']}“?",parent=self.app): return
            model.save_location(self.M,row['kind'],row['id'],match['gps'],model.snapshot(row),'ruian',match['code'])
            self.app.refresh_all(); self.refresh()
        except (ValueError,sqlite3.Error,OSError) as exc: self.warn(exc)

    def start_job(self, function, kind):
        if self.job_running:
            return self.warn('Počkejte na dokončení právě běžící operace.')
        self.job_running = True
        if self.poll_after is None: self.poll_after = self.page.after(150,self.poll)
        generation = self.generation
        def worker():
            try: result = function(lambda text:self.jobs.put(('progress',generation,text)))
            except Exception as exc: self.jobs.put(('error',generation,str(exc)))
            else: self.jobs.put((kind,generation,result))
        threading.Thread(target=worker,daemon=True).start()

    def download(self):
        self.start_job(ruian.download,'index')

    def import_zip(self):
        path = filedialog.askopenfilename(parent=self.app,title='Adresní místa RÚIAN – ZIP ČÚZK',filetypes=[('ZIP ČÚZK','*.zip')])
        if path: self.start_job(lambda progress:ruian.import_zip(path,progress),'index')

    def batch_lookup(self):
        try: access.require(self.M,'map')
        except ValueError as exc: return self.warn(exc)
        candidates = [dict(r) for r in self.records.values() if not r['gps_coordinates'] and r['address'] and access.level(self.M,model.TABLES[r['kind']]) >= access.EDIT]
        def lookup(progress):
            matched = []
            for index,row in enumerate(candidates):
                matches = ruian.lookup(row['address'])
                if len(matches) == 1: matched.append((row,matches[0]))
                if index % 25 == 0: progress(f'Porovnávám adresy: {index+1}/{len(candidates)}…')
            return matched
        self.start_job(lookup,'matches')

    def poll(self):
        self.poll_after = None
        for _ in range(50):
            try: kind,generation,result = self.jobs.get_nowait()
            except queue.Empty: break
            if kind != 'progress': self.job_running = False
            if generation != self.generation: continue
            if kind == 'progress': self.status.set(result)
            elif kind == 'error': self.warn(result)
            elif kind == 'index': self.status.set(f'Adresář připraven: {result:,} adres. {ruian.LICENSE}. Nyní můžete doplnit polohy podle adres.')
            elif kind == 'matches':
                if not result: self.warn('Žádná chybějící poloha nemá jednoznačnou shodu. Zkontrolujte úplné adresy včetně PSČ.')
                elif self.M.messagebox.askyesno('Doplnit polohy',f'Nalezeno {len(result)} jednoznačných shod. Uložit polohy k těmto záznamům? Existující GPS se nepřepíšou.',parent=self.app):
                    self.job_running = True
                    self.apply_matches(result,generation)
        if self.job_running or not self.jobs.empty():
            self.poll_after = self.page.after(150,self.poll)

    def apply_matches(self, matches, generation, offset=0, saved=0):
        self._apply_after = None
        if generation != self.generation:
            self.job_running = False
            return  # A user switch cancels the remaining writes.
        end = min(offset+10,len(matches))
        for row,match in matches[offset:end]:
            try:
                model.save_location(self.M,row['kind'],row['id'],match['gps'],model.snapshot(row),'ruian',match['code'])
                saved += 1
            except (ValueError,sqlite3.Error):
                pass  # Count stale/denied rows in the completion message.
        if end < len(matches):
            self.status.set(f'Ukládám polohy: {end}/{len(matches)}…')
            self._apply_after = self.page.after(10,lambda:self.apply_matches(matches,generation,end,saved))
        else:
            self.job_running = False
            self.app.refresh_all(); self.refresh()
            self.status.set(f'Uloženo {saved} poloh; {len(matches)-saved} záznamů přeskočeno kvůli změně údajů nebo oprávnění.')


def apply(M):
    if getattr(M,'_map_835',False): return
    previous_schema = M.ensure_schema
    def schema():
        result = previous_schema()
        with closing(M.db()) as con, con:
            model.ensure_schema(con)
        return result
    M.ensure_schema = schema
    previous_build = M.App.build
    def build(app,*args,**kwargs):
        result = previous_build(app,*args,**kwargs)
        page = ttk.Frame(app.pages,style='App.TFrame')
        app.tabs['map'] = page
        app.map_workspace = Workspace(M,app,page)
        page.grid(row=0,column=0,sticky='nsew'); page.lower()
        navigation.register_page(app,'map','Mapa')
        return result
    M.App.build = build
    previous_show = M.App.show_page
    def show(app,key,*args,**kwargs):
        result = previous_show(app,key,*args,**kwargs)
        workspace = getattr(app,'map_workspace',None)
        if workspace:
            if getattr(app,'_current_page',None) == 'map': workspace.activate()
            else:
                workspace.cancel_pick(); workspace.send({'type':'visible','value':False})
        return result
    M.App.show_page = show
    previous_refresh = M.App.refresh_all
    def refresh(app,*args,**kwargs):
        result = previous_refresh(app,*args,**kwargs)
        workspace = getattr(app,'map_workspace',None)
        if workspace and getattr(app,'_current_page',None) == 'map': workspace.refresh()
        return result
    M.App.refresh_all = refresh
    M._map_835 = True
