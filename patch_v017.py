from __future__ import annotations
import re
from pathlib import Path


def apply_patch(root):
    root = Path(root)

    # version + schema version
    p = root / 'src' / 'constants.py'
    s = p.read_text(encoding='utf-8')
    s = re.sub(r"APP_VERSION\s*=\s*'[^']+'", "APP_VERSION = '0.1.7'", s, count=1)
    s = re.sub(r"DB_SCHEMA_VERSION\s*=\s*\d+", "DB_SCHEMA_VERSION = 2", s, count=1)
    p.write_text(s, encoding='utf-8')

    # future-ready item columns + migration
    p = root / 'src' / 'db.py'
    s = p.read_text(encoding='utf-8')
    old = "    profit_total REAL DEFAULT 0,\n    source_import_id INTEGER,"
    new = "    profit_total REAL DEFAULT 0,\n    sales_unit REAL,\n    sales_total REAL,\n    cost_unit REAL,\n    cost_total REAL,\n    margin_amount REAL,\n    margin_percent REAL,\n    source_import_id INTEGER,"
    if 'sales_total REAL' not in s:
        if old not in s:
            raise RuntimeError('v0.1.7: profit_items schema block not found')
        s = s.replace(old, new, 1)
    old = "            con.executescript(SCHEMA)\n            con.execute('INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)', ('schema_version', str(DB_SCHEMA_VERSION)))\n"
    new = "            con.executescript(SCHEMA)\n            cols={r[1] for r in con.execute('PRAGMA table_info(profit_items)').fetchall()}\n            for name, sql_type in (('sales_unit','REAL'),('sales_total','REAL'),('cost_unit','REAL'),('cost_total','REAL'),('margin_amount','REAL'),('margin_percent','REAL')):\n                if name not in cols:\n                    con.execute(f'ALTER TABLE profit_items ADD COLUMN {name} {sql_type}')\n            con.execute('INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)', ('schema_version', str(DB_SCHEMA_VERSION)))\n"
    if "PRAGMA table_info(profit_items)" not in s:
        if old not in s:
            raise RuntimeError('v0.1.7: db migration block not found')
        s = s.replace(old, new, 1)
    p.write_text(s, encoding='utf-8')

    # analytics detail method
    p = root / 'src' / 'analytics.py'
    s = p.read_text(encoding='utf-8')
    if '    def document_detail(self, doc_no):' not in s:
        marker = '    def products(self, year, month, limit=100):\n'
        if marker not in s:
            raise RuntimeError('v0.1.7: analytics marker not found')
        method = '''    def document_detail(self, doc_no):
        rows = self.db.query(
            """SELECT d.doc_no,d.doc_date,d.customer,d.description,d.center,d.project,d.note,
                      d.base_amount,d.total_amount,COALESCE(p.profit_total,0) profit_total,
                      CASE WHEN d.base_amount<>0 AND p.doc_no IS NOT NULL
                           THEN p.profit_total/d.base_amount*100 ELSE NULL END margin_percent,
                      CASE WHEN p.doc_no IS NOT NULL THEN 1 ELSE 0 END profit_available
               FROM delivery_notes d LEFT JOIN profit_documents p ON p.doc_no=d.doc_no
               WHERE d.doc_no=?""", (doc_no,)
        )
        if not rows:
            return None
        items=[dict(r) for r in self.db.query(
            """SELECT id,doc_no,code,name,item_text,quantity,profit_unit,profit_total,
                      sales_unit,sales_total,cost_unit,cost_total,margin_amount,margin_percent
               FROM profit_items WHERE doc_no=? ORDER BY id""", (doc_no,)
        )]
        out=dict(rows[0]); out['items']=items
        return out

'''
        s = s.replace(marker, method + marker, 1)
    p.write_text(s, encoding='utf-8')

    # UI helper + click-through document detail
    p = root / 'src' / 'ui.py'
    s = p.read_text(encoding='utf-8')
    if 'def fmt_num(' not in s:
        marker = 'def fmt_pct(v):\n'
        if marker not in s:
            raise RuntimeError('v0.1.7: fmt_pct marker not found')
        helper = "def fmt_num(v):\n    try:\n        n=float(v); txt=f'{n:,.2f}'.replace(',', ' ').replace('.', ','); return txt.rstrip('0').rstrip(',')\n    except Exception:\n        return str(v if v is not None else '—')\n\n"
        s = s.replace(marker, helper + marker, 1)

    if '    def open_document_detail(self,doc_no):' not in s:
        old1 = "        p=Panel(root,'Největší doklady'); p.pack(fill='both',expand=True,pady=(12,0)); tree=self._tree(p.body,('center','doc','customer','project','amount','profit','margin'),('Středisko','DL','Zákazník','Projekt','Částka','Zisk','Marže'),(120,105,220,220,130,120,85),12,anchors=('w','w','w','w','e','e','e'))\n        for x in self.analytics.top_documents(y,m,self.mode_key(),limit=50): tree.insert('', 'end',values=(center_display(x['center']),x['doc_no'],x['customer'],x['project'],fmt_money(x['base_amount']),fmt_money(x['profit']),fmt_pct(x['margin'])))\n\n"
        if old1 not in s:
            raise RuntimeError('v0.1.7: largest-documents block not found')
        block = '''        p=Panel(root,'Největší doklady'); p.pack(fill='both',expand=True,pady=(12,0)); tree=self._tree(p.body,('center','doc','customer','project','amount','profit','margin'),('Středisko','DL','Zákazník','Projekt','Částka','Zisk','Marže'),(120,105,220,220,130,120,85),12,anchors=('w','w','w','w','e','e','e'))
        doc_map={}
        for x in self.analytics.top_documents(y,m,self.mode_key(),limit=50):
            iid=tree.insert('', 'end',values=(center_display(x['center']),x['doc_no'],x['customer'],x['project'],fmt_money(x['base_amount']),fmt_money(x['profit']),fmt_pct(x['margin'])))
            doc_map[iid]=x['doc_no']
        def open_doc(event=None):
            iid=tree.focus()
            if not iid and tree.selection(): iid=tree.selection()[0]
            doc_no=doc_map.get(iid)
            if doc_no: self.open_document_detail(doc_no)
        tree.bind('<Double-1>',open_doc); tree.bind('<Return>',open_doc)
        tk.Label(p.body,text='Dvojklikem na řádek otevřete položky dodacího listu.',bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',8),anchor='w').pack(fill='x',pady=(6,0))

'''
        s = s.replace(old1, block, 1)
        marker = '    def page_customers(self):\n'
        if marker not in s:
            raise RuntimeError('v0.1.7: page_customers marker not found')
        detail = '''    def open_document_detail(self,doc_no):
        data=self.analytics.document_detail(doc_no)
        if not data:
            messagebox.showinfo('Dodací list','Dodací list se nepodařilo najít v databázi.'); return
        win=tk.Toplevel(self); win.title(f"{doc_no} – položky dodacího listu"); win.geometry('1380x780'); win.minsize(1050,650); win.configure(bg=COLORS['bg'])
        try: win.transient(self)
        except Exception: pass
        head=tk.Frame(win,bg=COLORS['bg']); head.pack(fill='x',padx=20,pady=(18,8))
        tk.Label(head,text=f"Dodací list {doc_no}",bg=COLORS['bg'],fg=COLORS['text'],font=('Calibri',20,'bold')).pack(anchor='w')
        subtitle=f"{data.get('customer') or '—'} · {data.get('doc_date') or '—'} · {center_display(data.get('center'))}"
        tk.Label(head,text=subtitle,bg=COLORS['bg'],fg=COLORS['muted'],font=('Calibri',10)).pack(anchor='w',pady=(2,0))
        if data.get('description'): tk.Label(head,text=data.get('description'),bg=COLORS['bg'],fg=COLORS['text'],font=('Calibri',10),anchor='w').pack(anchor='w',pady=(5,0))
        cards=tk.Frame(win,bg=COLORS['bg']); cards.pack(fill='x',padx=20,pady=(0,12))
        available=bool(data.get('profit_available')); margin=data.get('margin_percent')
        vals=[('Částka bez DPH',fmt_money(data.get('base_amount') or 0),'hodnota DL'),('Zisk',fmt_money(data.get('profit_total') or 0) if available else '—','z reportu Zisk (zásoby)' if available else 'ziskový report chybí'),('Marže',fmt_pct(margin) if margin is not None else '—','marže celého DL'),('Položek',str(len(data.get('items') or [])),'položkových řádků')]
        for i,(a,b,c) in enumerate(vals): Card(cards,a,b,c,accent=COLORS['amber'] if i in (1,2) else COLORS['teal']).grid(row=0,column=i,sticky='nsew',padx=(0 if i==0 else 7,0)); cards.grid_columnconfigure(i,weight=1)
        panel=Panel(win,'Položky dodacího listu'); panel.pack(fill='both',expand=True,padx=20,pady=(0,16))
        tk.Label(panel.body,text='Prodejní cena, náklad a položková marže jsou připravené pro budoucí export z POHODY. Pokud je zdroj zatím neobsahuje, zobrazí se —.',bg=COLORS['panel'],fg=COLORS['amber'],font=('Calibri',8),anchor='w').pack(fill='x',pady=(0,6))
        tree=self._tree(panel.body,('code','name','item_text','qty','sales','cost','profit_unit','profit','margin'),('Kód','Název','Poznámka / balení','Množství','Prodej','Náklad','Zisk / j.','Zisk','Marže'),(160,330,190,90,115,115,105,115,85),height=16,anchors=('w','w','w','e','e','e','e','e','e'))
        mm=lambda v: fmt_money(v) if v is not None else '—'; mp=lambda v: fmt_pct(v) if v is not None else '—'
        items=data.get('items') or []
        for item in items:
            tree.insert('', 'end',values=(item.get('code') or '—',item.get('name') or '—',item.get('item_text') or '',fmt_num(item.get('quantity') or 0),mm(item.get('sales_total')),mm(item.get('cost_total')),fmt_money(item.get('profit_unit') or 0,2),fmt_money(item.get('profit_total') or 0),mp(item.get('margin_percent'))))
        if not items: tk.Label(panel.body,text='Pro tento dodací list nejsou položková data z reportu Zisk (zásoby) dostupná.',bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',10)).pack(anchor='w',pady=10)

'''
        s = s.replace(marker, detail + marker, 1)
    p.write_text(s, encoding='utf-8')

    (root/'ZMENY_0.1.7.txt').write_text('TURTO – Měsíční přehledy v0.1.7\n- Dvojklik na Největší doklady otevře detail DL.\n- Detail zobrazuje položky, množství, zisk/jednotku a zisk položky.\n- Připravené sloupce pro budoucí prodejní cenu, náklad a položkovou marži.\n', encoding='utf-8')
