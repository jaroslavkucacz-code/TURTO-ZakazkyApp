from __future__ import annotations

import re
from pathlib import Path

MANIFEST_URL = 'https://raw.githubusercontent.com/jaroslavkucacz-code/TURTO-ZakazkyApp/mesicni-prehledy-stable/update_manifest.json'


def _replace_once(text: str, old: str, new: str) -> str:
    if new in text:
        return text
    if old not in text:
        return text
    return text.replace(old, new, 1)


def apply_patch(root: str | Path) -> None:
    root = Path(root)
    constants = root / 'src' / 'constants.py'
    config = root / 'src' / 'config.py'
    ui = root / 'src' / 'ui.py'

    if constants.exists():
        s = constants.read_text(encoding='utf-8')
        s = re.sub(r"APP_VERSION\s*=\s*'[^']+'", "APP_VERSION = '0.1.4'", s, count=1)
        constants.write_text(s, encoding='utf-8')

    if config.exists():
        s = config.read_text(encoding='utf-8')
        s = re.sub(r"'update_manifest_url':\s*'[^']*'", f"'update_manifest_url': '{MANIFEST_URL}'", s, count=1)
        fallback = """    # Od v0.1.4 je stabilní aktualizační kanál vestavěný. Starší config.json\n    # může obsahovat prázdnou hodnotu; v takovém případě ji automaticky opravíme.\n    if not str(cfg.get('update_manifest_url','')).strip():\n        cfg['update_manifest_url'] = DEFAULT_CONFIG['update_manifest_url']\n    return cfg\n"""
        if "cfg['update_manifest_url'] = DEFAULT_CONFIG['update_manifest_url']" not in s:
            s = s.replace('    return cfg\n', fallback, 1)
        config.write_text(s, encoding='utf-8')

    if ui.exists():
        s = ui.read_text(encoding='utf-8')
        old_tree = """    def _tree(self,parent,cols,headings,widths=None,height=8,anchors=None):\n        tree=ttk.Treeview(parent,columns=cols,show='headings',height=height,style='Dark.Treeview')\n        for i,c in enumerate(cols):\n            anchor=(anchors[i] if anchors else ('w' if i==0 else 'e'))\n            tree.heading(c,text=headings[i],anchor=anchor)\n            tree.column(c,width=(widths[i] if widths else 120),anchor=anchor,minwidth=45)\n        tree.pack(fill='both',expand=True)\n        return tree\n"""
        new_tree = """    def _tree(self,parent,cols,headings,widths=None,height=8,anchors=None):\n        # Jednotná tabulka s okamžitým vyhledáváním. Filtruje všechny sloupce,\n        # takže funguje stejně pro zákazníka, číslo DL, částku, obchodníka i stav.\n        search_bar=tk.Frame(parent,bg=COLORS['panel'])\n        search_bar.pack(fill='x',pady=(0,7))\n        tk.Label(search_bar,text='Hledat',bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',9)).pack(side='left',padx=(0,7))\n        search_var=tk.StringVar()\n        search_entry=tk.Entry(search_bar,textvariable=search_var,bg=COLORS['panel_soft'],fg=COLORS['text'],insertbackground=COLORS['text'],relief='flat',font=('Calibri',10))\n        search_entry.pack(side='left',fill='x',expand=True,ipady=5)\n        result_lbl=tk.Label(search_bar,text='',bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',8))\n        result_lbl.pack(side='right',padx=(9,0))\n        clear_btn=tk.Button(search_bar,text='×',command=lambda: search_var.set(''),bg=COLORS['panel_soft'],fg=COLORS['muted'],activebackground=COLORS['border'],activeforeground=COLORS['text'],relief='flat',bd=0,font=('Calibri',13,'bold'),width=2)\n        clear_btn.pack(side='right',padx=(6,0))\n\n        holder=tk.Frame(parent,bg=COLORS['panel'])\n        holder.pack(fill='both',expand=True)\n        tree=ttk.Treeview(holder,columns=cols,show='headings',height=height,style='Dark.Treeview')\n        for i,c in enumerate(cols):\n            anchor=(anchors[i] if anchors else ('w' if i==0 else 'e'))\n            tree.heading(c,text=headings[i],anchor=anchor)\n            tree.column(c,width=(widths[i] if widths else 120),anchor=anchor,minwidth=45)\n        scroll=ttk.Scrollbar(holder,orient='vertical',command=tree.yview)\n        tree.configure(yscrollcommand=scroll.set)\n        tree.pack(side='left',fill='both',expand=True)\n        scroll.pack(side='right',fill='y')\n\n        original_insert=tree.insert\n        tree._search_iids=[]\n        def tracked_insert(parent_iid,index,**kw):\n            iid=original_insert(parent_iid,index,**kw)\n            if not parent_iid:\n                tree._search_iids.append(iid)\n                if search_var.get().strip():\n                    tree.after_idle(apply_filter)\n                else:\n                    result_lbl.config(text=f'{len(tree._search_iids)} řádků')\n            return iid\n        tree.insert=tracked_insert\n\n        def normalize(value):\n            return str(value if value is not None else '').lower().replace('\\u00a0',' ').strip()\n\n        def apply_filter(*_):\n            q=normalize(search_var.get())\n            visible=[]\n            for iid in tree._search_iids:\n                vals=tree.item(iid,'values')\n                hay=' | '.join(normalize(v) for v in vals)\n                if not q or q in hay:\n                    visible.append(iid)\n            visible_set=set(visible)\n            for iid in tree._search_iids:\n                if iid in visible_set:\n                    tree.move(iid,'','end')\n                else:\n                    tree.detach(iid)\n            total=len(tree._search_iids)\n            result_lbl.config(text=(f'{len(visible)} / {total} řádků' if q else f'{total} řádků'))\n\n        search_var.trace_add('write',apply_filter)\n        tree.search_var=search_var\n        tree.search_entry=search_entry\n        tree.apply_filter=apply_filter\n        return tree\n"""
        s = _replace_once(s, old_tree, new_tree)

        old_settings = """        up=Panel(root,'Online aktualizace'); up.pack(fill='x',pady=(12,0))\n        update_url=self.cfg.get('update_manifest_url','').strip()\n        state_text='Aktivní – aktualizační kanál je nastaven' if update_url else 'Neaktivní – pro tento program ještě není nastaven online manifest'\n        state_color=COLORS['teal'] if update_url else COLORS['amber']\n        tk.Label(up.body,text=f'Aktuální verze: {APP_VERSION}',bg=COLORS['panel'],fg=COLORS['text']).grid(row=0,column=0,sticky='w')\n        tk.Label(up.body,text=state_text,bg=COLORS['panel'],fg=state_color,font=('Calibri',9,'bold')).grid(row=0,column=1,columnspan=2,sticky='e')\n        tk.Label(up.body,text='URL manifestu aktualizace',bg=COLORS['panel'],fg=COLORS['muted']).grid(row=1,column=0,sticky='w',pady=(10,3))\n        self.update_entry=tk.Entry(up.body,bg=COLORS['panel_soft'],fg=COLORS['text'],insertbackground=COLORS['text'],relief='flat'); self.update_entry.insert(0,update_url); self.update_entry.grid(row=2,column=0,sticky='ew',ipady=6)\n        up.body.grid_columnconfigure(0,weight=1)\n        tk.Button(up.body,text='Uložit',command=self.save_update_url,bg=COLORS['panel_soft'],fg=COLORS['text'],relief='flat',padx=12,pady=7).grid(row=2,column=1,padx=8)\n        tk.Button(up.body,text='Zkontrolovat aktualizace',command=self.check_updates,bg=COLORS['teal'],fg='#06251D',relief='flat',padx=12,pady=7,font=('Calibri',10,'bold')).grid(row=2,column=2)\n"""
        new_settings = """        up=Panel(root,'Online aktualizace'); up.pack(fill='x',pady=(12,0))\n        update_url=self.cfg.get('update_manifest_url','').strip()\n        state_text='Aktivní – GitHub aktualizační kanál je připojen' if update_url else 'Aktualizační kanál není dostupný'\n        state_color=COLORS['teal'] if update_url else COLORS['amber']\n        tk.Label(up.body,text=f'Aktuální verze: {APP_VERSION}',bg=COLORS['panel'],fg=COLORS['text'],font=('Calibri',10,'bold')).grid(row=0,column=0,sticky='w')\n        tk.Label(up.body,text=state_text,bg=COLORS['panel'],fg=state_color,font=('Calibri',9,'bold')).grid(row=0,column=1,sticky='e')\n        tk.Label(up.body,text='Kanál: TURTO-Mesicni-Prehledy · stabilní',bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',9)).grid(row=1,column=0,sticky='w',pady=(8,0))\n        tk.Label(up.body,text='Kontrola probíhá automaticky po spuštění programu.',bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',9)).grid(row=2,column=0,sticky='w',pady=(2,0))\n        up.body.grid_columnconfigure(0,weight=1)\n        tk.Button(up.body,text='Zkontrolovat aktualizace',command=self.check_updates,bg=COLORS['teal'],fg='#06251D',relief='flat',padx=14,pady=8,font=('Calibri',10,'bold')).grid(row=1,column=1,rowspan=2,padx=(14,0),sticky='e')\n"""
        s = _replace_once(s, old_settings, new_settings)

        old_update = """    def save_update_url(self): self.cfg['update_manifest_url']=self.update_entry.get().strip(); save_config(self.cfg); messagebox.showinfo('Aktualizace','Nastavení bylo uloženo.'); self.refresh_current()\n    def check_updates(self):\n        try:\n            r=check_update(self.update_entry.get().strip())\n            if not r.get('configured'): messagebox.showinfo('Aktualizace','URL manifestu zatím není nastaveno. Po vytvoření GitHub release ho sem doplníme.')\n"""
        new_update = """    def check_updates(self):\n        try:\n            r=check_update(self.cfg.get('update_manifest_url','').strip())\n            if not r.get('configured'): messagebox.showinfo('Aktualizace','Online aktualizační kanál není dostupný.')\n"""
        s = _replace_once(s, old_update, new_update)
        ui.write_text(s, encoding='utf-8')

    (root / 'ZMENY_0.1.4.txt').write_text(
        'TURTO – Měsíční přehledy v0.1.4\n'
        '- Okamžité vyhledávání ve všech tabulkách napříč všemi sloupci.\n'
        '- Počet zobrazených / celkových řádků u filtru.\n'
        '- Svislé posuvníky u tabulek.\n'
        '- Pevně připojený online aktualizační kanál GitHub.\n',
        encoding='utf-8')
