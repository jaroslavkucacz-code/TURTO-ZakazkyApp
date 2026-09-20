"""Lazy map tab, canonical record dialogs and online address/parcel lookup."""
from __future__ import annotations

from contextlib import closing
import queue
import sqlite3
import threading
import tkinter as tk
from tkinter import ttk
import webbrowser
from urllib.parse import urlsplit

from . import model, online
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
        self.cancel_event = threading.Event()
        self.preview = None
        self.preview_target = None
        self.cadastre_choices = {}
        self.generation = 0
        self.loaded = False
        self.embedded = False
        self.last_applied_count = None
        self.last_preview_point = None
        self.basemap = tk.StringVar(value='map')
        self.last_basemap_state = None
        self.basemap_ready = None
        self.layer = tk.StringVar(value='Obojí')
        self.phase = tk.StringVar(value='Všechny stavy')
        self.supplying = tk.BooleanVar(value=False)
        self.query = tk.StringVar()
        self.start_from, self.start_to = tk.StringVar(), tk.StringVar()
        self.gps = tk.StringVar()
        self.selected_label = tk.StringVar(value='Vyberte záznam v seznamu nebo na mapě.')
        self.status = tk.StringVar(value='OpenFreeMap · adresy a parcely online z ČÚZK · GPS se ukládají v CRM.')
        self.batch_scope = tk.StringVar(value='Vybrané záznamy')
        self.cadastre_query = tk.StringVar()
        self.cadastre_choice = tk.StringVar()
        self.parcel_number = tk.StringVar()
        self.parcel_kind = tk.StringVar(value='Automaticky')
        self.preview_label = tk.StringVar(value='Nalezenou polohu nejprve zobrazte na mapě.')
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
        backgrounds = ttk.Frame(filters)
        backgrounds.grid(row=1,column=0,columnspan=2,sticky='w',pady=(7,0))
        ttk.Label(backgrounds,text='Podklad:').pack(side='left',padx=(0,10))
        self.basemap_buttons = {}
        for label,value in (('Mapa','map'),('Ortofoto ČR','orthophoto')):
            button=ttk.Radiobutton(backgrounds,text=label,variable=self.basemap,value=value,command=self.change_basemap)
            button.pack(side='left',padx=(0,14)); self.basemap_buttons[value]=button
        ttk.Label(filters, text='Modrá: společnost · Zlatá: akce · Zelená: dodáváme · Šedá: ukončeno').grid(row=1, column=2, columnspan=6, sticky='w', pady=(7,0))
        panes = ttk.Panedwindow(page, orient='horizontal'); panes.grid(row=2, column=0, sticky='nsew', padx=12)
        left = ttk.Frame(panes, width=360); right = ttk.Frame(panes)
        panes.add(left, weight=1); panes.add(right, weight=3)
        left.columnconfigure(0, weight=1); left.rowconfigure(0, weight=3, minsize=105)
        left.rowconfigure(2, weight=2, minsize=75)
        self.tree = ttk.Treeview(left, columns=('name','state'), show='headings', selectmode='extended', height=5,
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
        self.details_body = details_body
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
        self.address_button = ttk.Button(edit, text='Dohledat GPS online', command=self.lookup); self.address_button.grid(row=4, column=0, sticky='ew', pady=3)
        ttk.Button(edit, text='Zrušit umístění', command=self.cancel_pick).grid(row=4, column=1, padx=(5,0), pady=3)
        batch = ttk.LabelFrame(details_body, text='Hromadné doplnění GPS', padding=10)
        batch.grid(row=1, column=0, sticky='ew', pady=(0,8)); batch.columnconfigure(0,weight=1)
        ttk.Combobox(batch, textvariable=self.batch_scope, state='readonly',
                     values=('Vybrané záznamy','Všechny ve filtru')).grid(row=0,column=0,sticky='ew')
        self.batch_button = ttk.Button(batch,text='Doplnit chybějící GPS online',command=self.batch_lookup)
        self.batch_button.grid(row=1,column=0,sticky='ew',pady=4)
        ttk.Label(batch,text='Více řádků vyberte pomocí Ctrl nebo Shift. Existující GPS se nepřepisují.',
                  wraplength=320).grid(row=2,column=0,sticky='w')
        parcel = ttk.LabelFrame(details_body,text='Najít parcelu v ČR',padding=10)
        parcel.grid(row=2,column=0,sticky='ew',pady=(0,8)); parcel.columnconfigure(0,weight=1)
        ttk.Label(parcel,text='Katastrální území – název nebo kód').grid(row=0,column=0,sticky='w')
        ku_entry=ttk.Entry(parcel,textvariable=self.cadastre_query)
        ku_entry.grid(row=1,column=0,sticky='ew'); ku_entry.bind('<Return>',lambda e:self.find_cadastres())
        ttk.Button(parcel,text='Vyhledat katastrální území',command=self.find_cadastres).grid(row=2,column=0,sticky='ew',pady=4)
        self.cadastre_box=ttk.Combobox(parcel,textvariable=self.cadastre_choice,state='readonly')
        self.cadastre_box.grid(row=3,column=0,sticky='ew')
        ttk.Label(parcel,text='Parcelní číslo (např. 123/4 nebo st. 123)').grid(row=4,column=0,sticky='w',pady=(8,0))
        number_entry=ttk.Entry(parcel,textvariable=self.parcel_number)
        number_entry.grid(row=5,column=0,sticky='ew'); number_entry.bind('<Return>',lambda e:self.find_parcel())
        ttk.Combobox(parcel,textvariable=self.parcel_kind,state='readonly',
                     values=('Automaticky','Pozemková','Stavební')).grid(row=6,column=0,sticky='ew',pady=4)
        ttk.Button(parcel,text='Najít parcelu a zobrazit bod',command=self.find_parcel).grid(row=7,column=0,sticky='ew')
        found=ttk.LabelFrame(details_body,text='Nalezená poloha – náhled',padding=10)
        found.grid(row=3,column=0,sticky='ew'); found.columnconfigure(0,weight=1)
        ttk.Label(found,textvariable=self.preview_label,wraplength=320).grid(row=0,column=0,sticky='w')
        self.save_found_button=ttk.Button(found,text='Uložit bod k vybranému záznamu',command=self.save_found,state='disabled')
        self.save_found_button.grid(row=1,column=0,sticky='ew',pady=4)
        ttk.Button(found,text='Zrušit náhled',command=self.clear_preview).grid(row=2,column=0,sticky='ew')
        ttk.Label(details_body,text='Online hledání používá ČÚZK. Odesílá se pouze hledaná adresa nebo parcela. '
                  'U parcely jde o definiční bod; místo stavby lze upřesnit kliknutím.',
                  wraplength=330).grid(row=4,column=0,sticky='w',pady=8)
        self.cadastre_query.trace_add('write',self.cadastre_edited)
        for variable in (self.cadastre_choice,self.parcel_number,self.parcel_kind):
            variable.trace_add('write',lambda *_:self.clear_preview())
        def bind_details(widget):
            widget.bind('<FocusIn>',lambda e:self.reveal_control(e.widget),add='+')
            for child in widget.winfo_children(): bind_details(child)
        bind_details(details_body)
        self.map_frame = tk.Frame(right, background='#edf2f4'); self.map_frame.pack(fill='both', expand=True)
        self.placeholder = ttk.Label(self.map_frame, text='Mapa se načte při otevření záložky.', anchor='center', wraplength=420)
        self.placeholder.pack(fill='both', expand=True, padx=15, pady=15)
        footer = ttk.Frame(page, padding=(12,8)); footer.grid(row=3, column=0, sticky='ew')
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status, wraplength=800).grid(row=0, column=0, sticky='w')
        self.stop_button=ttk.Button(footer,text='Zastavit hledání',command=self.cancel_job,state='disabled')
        self.stop_button.grid(row=1,column=0,sticky='w',pady=(4,0))
        ttk.Button(footer, text='Zobrazit zdroje', command=self.sources).grid(row=0, column=1, padx=5)
        self.runtime_button = ttk.Button(footer, text='Instalovat WebView2', command=lambda:webbrowser.open('https://developer.microsoft.com/microsoft-edge/webview2/'))
        self.runtime_button.grid(row=0,column=2); self.runtime_button.grid_remove()
        self.poll_after = None
        page.bind('<Destroy>', self.destroy, add='+')

    def destroy(self, event):
        if event.widget is not self.page: return
        self.generation += 1
        self.cancel_event.set()
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
        self.cancel_job(quiet=True)
        self.clear_preview()
        self.cadastre_query.set(''); self.parcel_number.set('')
        self.records.clear(); self.pending_pick = None
        # Destroy the old user's renderer, including queued pipe messages/popups.
        if self.bridge: self.bridge.close()
        self.bridge = None; self.loaded = False
        self.tree.delete(*self.tree.get_children())
        self.gps.set(''); self.selected_label.set('Vyberte záznam v seznamu nebo na mapě.')
        self.last_basemap_state = self.basemap_ready = None
        if getattr(self.app,'_current_page',None) == 'map' and access.level(self.M,'map') >= access.READ:
            self.activate()
        else: self.send({'type':'visible','value':False})

    def selected(self):
        selection = self.tree.selection()
        return self.records.get(selection[0]) if len(selection) == 1 else None

    def select(self, event=None):
        self.cancel_pick()
        row = self.selected()
        self.gps.set(row['gps_coordinates'] or '' if row else '')
        self.selected_label.set('\n'.join(filter(None,(row['title'],row['address'],row.get('map_label','')))) if row else
                                f'Vybráno {len(self.tree.selection())} záznamů. Pro jednotlivou úpravu vyberte jeden.')
        can_write = bool(row and access.level(self.M,'map') >= access.EDIT and access.level(self.M,model.TABLES[row['kind']]) >= access.EDIT)
        for control in (self.gps_entry, self.save_button, self.pick_button, self.address_button):
            control.configure(state='normal' if can_write else 'disabled')
        self.save_found_button.configure(state='normal' if can_write and self.preview else 'disabled')
        self.batch_button.configure(state='normal' if access.level(self.M,'map') >= access.EDIT else 'disabled')

    def refresh(self):
        try:
            access.require(self.M,'map',write=False)
            current = self.tree.selection()
            records = model.rows(self.M, layer={'Obojí':'both','Společnosti':'company','Akce':'project'}[self.layer.get()],
                phase='' if self.phase.get() == 'Všechny stavy' else self.phase.get(), supplying=self.supplying.get(),
                start_from=self.start_from.get(), start_to=self.start_to.get(), query=self.query.get())
            self.records = {r['key']:r for r in records}
            self.tree.delete(*self.tree.get_children())
            for row in records:
                state = row['location_state'] if not row['coordinates'] else ('Společnost' if row['kind']=='company' else row['phase'] + (' · dodáváme' if row['supplying'] else ''))
                self.tree.insert('', 'end', iid=row['key'], values=(row['title'], state))
            self.tree.selection_set([key for key in current if key in self.records])
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
        self.loaded = False
        self.last_preview_point = None
        self.last_basemap_state = self.basemap_ready = None
        self.send({'type':'reload'})
        if not self.bridge: self.activate()
        else: self.refresh()

    def reset(self):
        self.query.set(''); self.phase.set('Všechny stavy'); self.supplying.set(False)
        self.start_from.set(''); self.start_to.set('')
        self.refresh(); self.send({'type':'fit'})

    def change_basemap(self):
        self.basemap_ready = None
        self.send({'type':'basemap','value':self.basemap.get()})

    def message(self, event):
        kind = event.get('type')
        if kind == 'ready':
            self.change_basemap(); self.refresh()
        elif kind == 'embedded': self.embedded = True
        elif kind == 'loaded':
            self.loaded = True
            if self.preview:
                self.send({'type':'preview','point':self.preview['coordinates'],'label':self.preview['label']})
        elif kind == 'data-applied': self.last_applied_count = event.get('count')
        elif kind == 'preview-applied': self.last_preview_point = event.get('point')
        elif kind == 'basemap-applied': self.last_basemap_state = event
        elif kind == 'basemap-ready': self.basemap_ready = event.get('value')
        elif kind == 'basemap-error': self.status.set(str(event.get('message','Ortofoto není dostupné.')))
        elif kind == 'attribution':
            url = str(event.get('url','')); parsed = urlsplit(url)
            if parsed.scheme == 'https' and parsed.hostname in {'openfreemap.org','openmaptiles.org','www.openstreetmap.org','maplibre.org','geoportal.cuzk.gov.cz'}:
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

    def sources(self):
        self.M.messagebox.showinfo('Zdroje mapy',
            'Mapový podklad: OpenFreeMap – https://openfreemap.org/\n'
            '© OpenMapTiles – https://openmaptiles.org/\n'
            '© OpenStreetMap contributors – https://www.openstreetmap.org/copyright\n\n'
            'Ortofoto ČR: © ČÚZK – https://geoportal.cuzk.gov.cz/\n'
            'https://ags.cuzk.gov.cz/arcgis1/rest/services/ORTOFOTO_WM/MapServer\n'
            'Ortofoto pokrývá Českou republiku. Mimo pokrytí zůstává běžná mapa.\n\n'
            'Adresní místa a parcely: ČÚZK – RÚIAN, licence CC BY 4.0.\n'
            'https://ags.cuzk.gov.cz/arcgis/rest/services/RUIAN/MapServer\n'
            'https://creativecommons.org/licenses/by/4.0/\n'
            'Vyhledávání je online, souřadnice WGS84. Odesílá se pouze hledaná adresa nebo parcela. '
            'Uložené GPS zůstávají v CRM. Parcela se umístí podle definičního bodu.',parent=self.app)

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
        if not row: return self.warn('Vyberte jeden záznam.')
        try:
            access.require(self.M,'map'); access.require(self.M,model.TABLES[row['kind']])
            if not row['address'].strip(): raise ValueError('Záznam nemá adresu. Pro stavbu bez adresy vyhledejte parcelu.')
            target = dict(row)
            self.start_job(lambda progress,cancel:(target,online.Client(cancel).addresses(target['address'])),'locations')
        except ValueError as exc: self.warn(exc)

    def cadastre_edited(self, *_):
        self.cadastre_choices.clear(); self.cadastre_choice.set('')
        self.cadastre_box.configure(values=())
        self.clear_preview()

    def find_cadastres(self):
        text = self.cadastre_query.get().strip()
        if not text: return self.warn('Vyplňte název nebo šestimístný kód katastrálního území.')
        self.start_job(lambda progress,cancel:(text,online.Client(cancel).cadastres(text)),'cadastres')

    def find_parcel(self):
        cadastre = self.cadastre_choices.get(self.cadastre_choice.get())
        if not cadastre: return self.warn('Nejdřív vyhledejte a vyberte katastrální území.')
        number = self.parcel_number.get()
        kind = {'Automaticky':'auto','Pozemková':'land','Stavební':'building'}[self.parcel_kind.get()]
        try: online.parse_parcel(number,kind)
        except ValueError as exc: return self.warn(exc)
        row = self.selected(); target = dict(row) if row else None
        inputs = (self.cadastre_choice.get(),number,self.parcel_kind.get())
        self.start_job(lambda progress,cancel:(inputs,target,online.Client(cancel).parcels(cadastre,number,kind)),'parcels')

    def clear_preview(self):
        self.preview = self.preview_target = None
        self.last_preview_point = None
        self.preview_label.set('Nalezenou polohu nejprve zobrazte na mapě.')
        self.save_found_button.configure(state='disabled')
        self.send({'type':'preview','point':None})

    def show_matches(self, matches, target):
        if not matches:
            return self.warn('Nenalezena platná poloha. Ověřte adresu, případně katastrální území, druh parcely a celé parcelní číslo.')
        current = self.selected()
        if target and (not current or current['key'] != target['key']):
            return self.warn('Výběr záznamu se během hledání změnil. Spusťte hledání znovu pro požadovaný záznam.')
        generation = self.generation
        chosen = matches[0] if len(matches) == 1 else None
        if chosen is None:
            dialog = tk.Toplevel(self.app); dialog.title('Vyberte nalezenou polohu')
            dialog.transient(self.app); dialog.geometry('760x350'); dialog.minsize(520,260)
            dialog.columnconfigure(0,weight=1); dialog.rowconfigure(1,weight=1)
            ttk.Label(dialog,text='Nalezeno více možností. Vyberte správnou adresu nebo parcelu.').grid(row=0,column=0,sticky='w',padx=12,pady=12)
            tree=ttk.Treeview(dialog,columns=('label',),show='headings',selectmode='browse',
                              name='layout__map__lookup_candidates')
            tree.heading('label',text='Nalezená poloha'); tree.column('label',width=680)
            tree.grid(row=1,column=0,sticky='nsew',padx=12)
            scroll=ttk.Scrollbar(dialog,orient='vertical',command=tree.yview); scroll.grid(row=1,column=1,sticky='ns')
            tree.configure(yscrollcommand=scroll.set)
            for i,match in enumerate(matches): tree.insert('','end',iid=str(i),values=(match['label'],))
            selection=[]
            def choose():
                if tree.selection(): selection.append(matches[int(tree.selection()[0])]); dialog.destroy()
            buttons=ttk.Frame(dialog); buttons.grid(row=2,column=0,sticky='e',padx=12,pady=12)
            ttk.Button(buttons,text='Zrušit',command=dialog.destroy).pack(side='right')
            ttk.Button(buttons,text='Zobrazit na mapě',command=choose).pack(side='right',padx=6)
            tree.bind('<Double-1>',lambda e:choose()); tree.bind('<Return>',lambda e:choose())
            self.send({'type':'visible','value':False})
            try:
                dialog.grab_set(); self.app.wait_window(dialog)
            finally: self.send({'type':'visible','value':True})
            if not selection or generation != self.generation: return
            chosen=selection[0]
        self.preview, self.preview_target = dict(chosen), target
        hint = '\nDefiniční bod parcely; přesné místo stavby lze upřesnit kliknutím.' if chosen['source']=='ruian-parcel' else ''
        self.preview_label.set(chosen['label']+'\nGPS: '+chosen['gps']+hint)
        self.send({'type':'preview','point':chosen['coordinates'],'label':chosen['label']})
        self.select()
        self.status.set('Nalezený bod je pouze náhled. Pro uložení použijte „Uložit bod k vybranému záznamu“.')
        self.page.after_idle(lambda:self.reveal_control(self.save_found_button))

    def reveal_control(self, widget):
        """Keep focused controls and the save action reachable on small screens."""
        self.details_body.update_idletasks()
        height = self.details_body.winfo_height()
        top = widget.winfo_rooty()-self.details_body.winfo_rooty()
        bottom = top+widget.winfo_height()
        start = self.details_canvas.yview()[0]*height
        visible = self.details_canvas.winfo_height()
        if top < start:
            self.details_canvas.yview_moveto(max(0,top-4)/max(1,height))
        elif bottom > start+visible:
            self.details_canvas.yview_moveto(max(0,bottom-visible+4)/max(1,height))

    def save_found(self):
        row = self.selected(); match = self.preview
        if not row or not match: return self.warn('Vyberte jeden záznam a vyhledejte jeho polohu.')
        expected = self.preview_target or dict(row)
        if expected['key'] != row['key']:
            return self.warn('Náhled patří k jinému záznamu. Pro tento záznam spusťte hledání znovu.')
        generation = self.generation
        prompt=f"{match['label']}\nGPS: {match['gps']}\n\nUložit k záznamu „{row['title']}“?"
        if row['gps_coordinates']: prompt+='\nTím nahradíte jeho dosavadní GPS.'
        if not self.M.messagebox.askyesno('Uložit nalezenou polohu',prompt,parent=self.app): return
        if generation != self.generation: return
        try:
            model.save_location(self.M,row['kind'],row['id'],match['gps'],model.snapshot(expected),match['source'],match['code'],match['label'])
            self.clear_preview(); self.app.refresh_all(); self.refresh()
            self.send({'type':'focus','key':row['key']})
        except (ValueError,sqlite3.Error) as exc: self.warn(exc)

    def start_job(self, function, kind):
        if self.job_running:
            return self.warn('Počkejte na dokončení právě běžící operace nebo ji zastavte.')
        try: access.require(self.M,'map',write=False)
        except ValueError as exc: return self.warn(exc)
        self.generation += 1
        if kind in ('locations','parcels'): self.clear_preview()
        self.cancel_event = threading.Event()
        cancel = self.cancel_event
        self.job_running = True
        self.stop_button.configure(state='normal',text='Zastavit hledání')
        self.status.set('Vyhledávám online v ČÚZK…')
        if self.poll_after is None: self.poll_after = self.page.after(150,self.poll)
        generation = self.generation
        def worker():
            try: result = function(lambda text:self.jobs.put(('progress',generation,text)),cancel)
            except online.Cancelled: self.jobs.put(('cancelled',generation,None))
            except Exception as exc: self.jobs.put(('error',generation,str(exc)))
            else: self.jobs.put((kind,generation,result))
        threading.Thread(target=worker,daemon=True).start()

    def cancel_job(self, quiet=False):
        self.cancel_event.set(); self.generation += 1
        self.job_running = False
        self.stop_button.configure(state='disabled')
        if not quiet:
            self.status.set('Operace zastavena. Již uložené GPS zůstávají v CRM.')

    def batch_lookup(self):
        try: access.require(self.M,'map')
        except ValueError as exc: return self.warn(exc)
        records = [self.records[k] for k in self.tree.selection() if k in self.records] if self.batch_scope.get()=='Vybrané záznamy' else list(self.records.values())
        candidates = [dict(r) for r in records if not r['gps_coordinates'] and r['address'].strip() and access.level(self.M,model.TABLES[r['kind']]) >= access.EDIT]
        if not candidates:
            return self.warn('Ve zvoleném rozsahu není žádný upravitelný záznam s adresou a bez GPS. Vyberte řádky nebo rozsah „Všechny ve filtru“.')
        self.start_job(lambda progress,cancel:online.batch_addresses(candidates,online.Client(cancel),progress),'matches')

    def poll(self):
        self.poll_after = None
        for _ in range(50):
            try: kind,generation,result = self.jobs.get_nowait()
            except queue.Empty: break
            if generation != self.generation: continue
            if kind != 'progress':
                self.job_running = False; self.stop_button.configure(state='disabled')
            if kind == 'progress': self.status.set(result)
            elif kind == 'error': self.status.set(str(result)); self.warn(result)
            elif kind == 'cadastres':
                text,rows = result
                if text != self.cadastre_query.get().strip(): continue
                self.cadastre_choices={row['label']:row for row in rows}
                self.cadastre_box.configure(values=tuple(self.cadastre_choices))
                self.cadastre_choice.set(rows[0]['label'] if len(rows)==1 else '')
                self.status.set(f'Nalezeno {len(rows)} katastrálních území. Vyberte území a zadejte parcelní číslo.')
                if not rows: self.warn('Katastrální území nebylo nalezeno. Zkontrolujte název nebo kód.')
                elif len(rows)>1: self.cadastre_box.focus_set()
            elif kind == 'locations': self.show_matches(result[1],result[0])
            elif kind == 'parcels':
                inputs,target,rows=result
                if inputs==(self.cadastre_choice.get(),self.parcel_number.get(),self.parcel_kind.get()):
                    self.show_matches(rows,target)
            elif kind == 'matches':
                matches=result['matches']
                summary=f"Nalezeno {len(matches)} jednoznačných shod. Ke kontrole: {result['skipped']}. Nezpracováno: {result['unprocessed']}."
                self.status.set(summary)
                if result['error']: summary+='\n'+result['error']
                if not matches: self.warn(summary+'\nOvěřte úplné adresy včetně PSČ nebo použijte jednotlivé dohledání.')
                elif self.M.messagebox.askyesno('Doplnit polohy',summary+'\n\nUložit nalezené polohy? Existující GPS se nepřepíšou.',parent=self.app) and generation==self.generation:
                    self.job_running = True
                    self.stop_button.configure(state='normal',text='Zastavit ukládání')
                    self.apply_matches(matches,generation)
        if self.job_running or not self.jobs.empty():
            self.poll_after = self.page.after(150,self.poll)

    def apply_matches(self, matches, generation, offset=0, saved=0):
        self._apply_after = None
        if generation != self.generation:
            return  # A user switch cancels the remaining writes.
        end = min(offset+10,len(matches))
        for row,match in matches[offset:end]:
            try:
                model.save_location(self.M,row['kind'],row['id'],match['gps'],model.snapshot(row),match['source'],match['code'],match['label'])
                saved += 1
            except (ValueError,sqlite3.Error):
                pass  # Count stale/denied rows in the completion message.
        if end < len(matches):
            self.status.set(f'Ukládám polohy: {end}/{len(matches)}…')
            self._apply_after = self.page.after(10,lambda:self.apply_matches(matches,generation,end,saved))
        else:
            self.job_running = False
            self.stop_button.configure(state='disabled')
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
