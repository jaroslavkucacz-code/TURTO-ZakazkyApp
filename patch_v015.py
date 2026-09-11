from __future__ import annotations

import re
from pathlib import Path

NEW_TREE = "    def _tree(self,parent,cols,headings,widths=None,height=8,anchors=None):\n        # Jednotná tabulka s okamžitým vyhledáváním a řazením klikem na záhlaví.\n        # Po opuštění záložky se tabulka znovu vytvoří, takže se řazení automaticky\n        # vrátí do původního pořadí dat.\n        search_bar=tk.Frame(parent,bg=COLORS['panel'])\n        search_bar.pack(fill='x',pady=(0,7))\n        tk.Label(search_bar,text='Hledat',bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',9)).pack(side='left',padx=(0,7))\n        search_var=tk.StringVar()\n        search_entry=tk.Entry(search_bar,textvariable=search_var,bg=COLORS['panel_soft'],fg=COLORS['text'],insertbackground=COLORS['text'],relief='flat',font=('Calibri',10))\n        search_entry.pack(side='left',fill='x',expand=True,ipady=5)\n        result_lbl=tk.Label(search_bar,text='',bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',8))\n        result_lbl.pack(side='right',padx=(9,0))\n        clear_btn=tk.Button(search_bar,text='×',command=lambda: search_var.set(''),bg=COLORS['panel_soft'],fg=COLORS['muted'],activebackground=COLORS['border'],activeforeground=COLORS['text'],relief='flat',bd=0,font=('Calibri',13,'bold'),width=2)\n        clear_btn.pack(side='right',padx=(6,0))\n\n        holder=tk.Frame(parent,bg=COLORS['panel'])\n        holder.pack(fill='both',expand=True)\n        tree=ttk.Treeview(holder,columns=cols,show='headings',height=height,style='Dark.Treeview')\n        tree._heading_text={c:headings[i] for i,c in enumerate(cols)}\n        tree._sort_col=None\n        tree._sort_reverse=False\n        for i,c in enumerate(cols):\n            anchor=(anchors[i] if anchors else ('w' if i==0 else 'e'))\n            tree.heading(c,text=headings[i],anchor=anchor)\n            tree.column(c,width=(widths[i] if widths else 120),anchor=anchor,minwidth=45)\n        scroll=ttk.Scrollbar(holder,orient='vertical',command=tree.yview)\n        tree.configure(yscrollcommand=scroll.set)\n        tree.pack(side='left',fill='both',expand=True)\n        scroll.pack(side='right',fill='y')\n\n        original_insert=tree.insert\n        tree._search_iids=[]\n        def tracked_insert(parent_iid,index,**kw):\n            iid=original_insert(parent_iid,index,**kw)\n            if not parent_iid:\n                tree._search_iids.append(iid)\n                if search_var.get().strip() or tree._sort_col:\n                    tree.after_idle(apply_filter)\n                else:\n                    result_lbl.config(text=f'{len(tree._search_iids)} řádků')\n            return iid\n        tree.insert=tracked_insert\n\n        def normalize(value):\n            return str(value if value is not None else '').lower().replace('\\u00a0',' ').strip()\n\n        def sort_value(value):\n            # Přirozené řazení pro datumy, částky, procenta a počty; ostatní jako text.\n            text=str(value if value is not None else '').strip()\n            if not text or text in ('—','-'):\n                return (3,'')\n            # ISO datum / datum s časem\n            import re\n            m=re.match(r'^(\\d{4})-(\\d{1,2})(?:-(\\d{1,2}))?',text)\n            if m:\n                y=int(m.group(1)); mo=int(m.group(2)); d=int(m.group(3) or 1)\n                return (0,y*10000+mo*100+d)\n            m=re.match(r'^(\\d{1,2})[.](\\d{1,2})[.](\\d{2,4})',text)\n            if m:\n                d=int(m.group(1)); mo=int(m.group(2)); y=int(m.group(3)); y += 2000 if y<100 else 0\n                return (0,y*10000+mo*100+d)\n            # Čísla, Kč, %, p.b., hvězdička u částečného zisku apod.\n            cleaned=text.replace('Kč','').replace('%','').replace('*','').replace(' ','').replace('\\u00a0','').replace(',','.').strip()\n            if re.fullmatch(r'[-+]?\\d+(?:\\.\\d+)?',cleaned):\n                try: return (1,float(cleaned))\n                except ValueError: pass\n            return (2,normalize(text))\n\n        def visible_iids():\n            q=normalize(search_var.get())\n            out=[]\n            for iid in tree._search_iids:\n                vals=tree.item(iid,'values')\n                hay=' | '.join(normalize(v) for v in vals)\n                if not q or q in hay:\n                    out.append(iid)\n            return out\n\n        def refresh_headings():\n            for c in cols:\n                label=tree._heading_text[c]\n                if c==tree._sort_col:\n                    label += '  ▼' if tree._sort_reverse else '  ▲'\n                tree.heading(c,text=label)\n\n        def sort_by_column(col):\n            if tree._sort_col==col:\n                tree._sort_reverse=not tree._sort_reverse\n            else:\n                tree._sort_col=col\n                tree._sort_reverse=False\n            refresh_headings()\n            apply_filter()\n\n        for c in cols:\n            # default argument je nutný, aby každý handler držel svůj sloupec\n            tree.heading(c,command=lambda column=c: sort_by_column(column))\n\n        def apply_filter(*_):\n            q=normalize(search_var.get())\n            visible=visible_iids()\n            if tree._sort_col:\n                idx=cols.index(tree._sort_col)\n                # Stabilní sort: při shodě zůstává původní pořadí z importu.\n                order={iid:i for i,iid in enumerate(tree._search_iids)}\n                visible.sort(key=lambda iid:(sort_value(tree.item(iid,'values')[idx]),order[iid]),reverse=tree._sort_reverse)\n            # detach/reattach zachová data i vazby na dvojklik zákazníka.\n            visible_set=set(visible)\n            for iid in tree._search_iids:\n                if iid not in visible_set:\n                    tree.detach(iid)\n            for iid in visible:\n                tree.move(iid,'','end')\n            total=len(tree._search_iids)\n            result_lbl.config(text=(f'{len(visible)} / {total} řádků' if q else f'{total} řádků'))\n\n        search_var.trace_add('write',apply_filter)\n        tree.search_var=search_var\n        tree.search_entry=search_entry\n        tree.apply_filter=apply_filter\n        tree.sort_by_column=sort_by_column\n        return tree\n"

def apply_patch(root: str | Path) -> None:
    root = Path(root)
    constants = root / 'src' / 'constants.py'
    ui = root / 'src' / 'ui.py'

    if constants.exists():
        s = constants.read_text(encoding='utf-8')
        if "APP_VERSION = '0.1.5'" not in s:
            s = re.sub(r"APP_VERSION\s*=\s*'[^']+'", "APP_VERSION = '0.1.5'", s, count=1)
            constants.write_text(s, encoding='utf-8')

    if ui.exists():
        s = ui.read_text(encoding='utf-8')
        marker = '    def _tree(self,parent,cols,headings,widths=None,height=8,anchors=None):'
        next_marker = '\n    def customer_table'
        if marker in s and next_marker in s:
            a = s.index(marker)
            b = s.index(next_marker, a)
            current = s[a:b]
            if current != NEW_TREE:
                s = s[:a] + NEW_TREE + s[b:]
                ui.write_text(s, encoding='utf-8')

    (root / 'ZMENY_0.1.5.txt').write_text(
        'TURTO – Měsíční přehledy v0.1.5\n'
        '- Řazení všech tabulek klikem na záhlaví.\n'
        '- Opakovaný klik přepíná vzestupné / sestupné řazení.\n'
        '- Aktivní sloupec je označen šipkou.\n'
        '- Řazení se po změně hlavní záložky vrací do výchozího stavu.\n'
        '- Řazení funguje společně s vyhledáváním.\n',
        encoding='utf-8')
