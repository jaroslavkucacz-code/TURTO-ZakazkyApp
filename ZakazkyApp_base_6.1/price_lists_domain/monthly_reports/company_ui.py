"""Explicit name matching and CRM document drill-down for imported companies."""
import tkinter as tk
from tkinter import ttk, messagebox

from .constants import COLORS
from .company_links import canonical_id
from ..platform.form_behavior_817 import wire_close


class CompanyLinkDialog(tk.Toplevel):
    def __init__(self, workspace, selected_name=None):
        super().__init__(workspace)
        self.workspace = workspace
        self.links = workspace.company_links
        self.rows = {}
        self.title('Párování firem s adresářem')
        self.geometry('1100x720'); self.minsize(820,570)
        self.transient(workspace.winfo_toplevel())
        self.grab_set()
        outer = ttk.Frame(self, padding=14); outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Firmy z POHODY → Adresář', font=('Calibri',16,'bold')).pack(anchor='w')
        ttk.Label(outer, text='Jednoznačné názvy se propojí automaticky. Více shod nebo odlišný název přiřaďte ručně.\n'
                  'Volba Nepárovat zabrání automatickému přiřazení. Změny potvrzujete tlačítkem; nové firmy se nevytvářejí.',
                  wraplength=1000, justify='left').pack(anchor='w', pady=(6,10))
        toolbar = ttk.Frame(outer); toolbar.pack(fill='x', pady=(0,8))
        self.summary = tk.StringVar()
        ttk.Label(toolbar,textvariable=self.summary).pack(side='left')
        ttk.Button(toolbar,text='Obnovit seznam',command=self.reload).pack(side='right')
        body = tk.Frame(outer,bg=COLORS['panel']); body.pack(fill='both', expand=True)
        self.tree = workspace._tree(body, ('source','company','ico','status'),
            ('Název v importu','Společnost v CRM','IČO v CRM','Párování'), (300,300,110,200),
            height=12, anchors=('w','w','w','w'))
        self.tree.bind('<<TreeviewSelect>>',self.select_row)
        choice = ttk.LabelFrame(outer,text='Přiřazení vybraného názvu',padding=10)
        choice.pack(fill='x',pady=(10,0))
        self.selected_text = tk.StringVar(value='Vyberte řádek v tabulce.')
        ttk.Label(choice,textvariable=self.selected_text,wraplength=970).pack(anchor='w',pady=(0,6))
        self.company_var = tk.StringVar()
        self.company_box = workspace.module.AutocompleteEntry(choice,textvariable=self.company_var,values=[])
        self.company_box.pack(fill='x')
        buttons = ttk.Frame(choice); buttons.pack(fill='x',pady=(8,0))
        self.save_button = ttk.Button(buttons,text='Uložit přiřazení',command=lambda:self.save('manual'))
        self.save_button.pack(side='left')
        ttk.Button(buttons,text='Nepárovat',command=lambda:self.save('ignored')).pack(side='left',padx=8)
        ttk.Button(buttons,text='Obnovit automatické párování',command=lambda:self.save('reset')).pack(side='left')
        ttk.Button(outer,text='Zavřít',command=self.close).pack(anchor='e',pady=(10,0))
        # This is a list editor with explicit per-row commits, not a save-on-close form.
        wire_close(self,self.close)
        self.reload(selected_name)

    def reload(self, selected_name=None):
        if selected_name is None:
            row = self.selected_row()
            selected_name = row['source_name'] if row else None
        companies = self.links.companies()
        self.labels = {}
        for cid, c in sorted(companies.items(),key=lambda item:(item[1]['official_name'].casefold(),item[0])):
            if canonical_id(companies,cid) != cid or not c['official_name'].strip():
                continue
            label = f"{c['official_name']} | IČO: {c['ico'] or '—'} | ID {cid}"
            if not c['active']:label += ' | Archiv'
            self.labels[label] = cid
        self.company_box.set_values(list(self.labels.items()))
        self.rows.clear()
        for iid in self.tree.get_children():self.tree.delete(iid)
        # Search can detach rows; clear those too before loading a fresh snapshot.
        for iid in self.tree._search_iids:
            if self.tree.exists(iid):self.tree.delete(iid)
        self.tree._search_iids.clear()
        resolved = self.links.resolve()
        linked = sum(bool(r['company_id']) for r in resolved.values())
        pending = sum(r['status'] in ('ambiguous','unmatched','missing') for r in resolved.values())
        self.summary.set(f'Názvů: {len(resolved)}   •   Propojeno: {linked}   •   K dořešení: {pending}')
        chosen = None
        for index, row in enumerate(resolved.values()):
            c = row['company'] or {}
            iid = self.tree.insert('','end',iid=f'link{index}',values=(row['source_name'],
                c.get('official_name','—'),c.get('ico',''),row['status_text']))
            self.rows[iid] = row
            if row['source_name'] == selected_name:chosen = iid
        self.tree.apply_filter()
        if chosen and chosen in self.tree.get_children():
            self.tree.selection_set(chosen);self.tree.focus(chosen);self.tree.see(chosen)
        self.select_row()

    def selected_row(self):
        selection = self.tree.selection()
        return self.rows.get(selection[0]) if selection else None

    def select_row(self, event=None):
        row = self.selected_row()
        self.selected_text.set(row['source_name'] if row else 'Vyberte řádek v tabulce.')
        cid = row['company_id'] if row else None
        self.company_var.set(next((label for label, target in self.labels.items() if target == cid),'') if cid else '')

    def save(self, mode):
        row = self.selected_row()
        if not row:
            messagebox.showinfo('Párování firem','Nejprve vyberte název z importu.',parent=self)
            return False
        cid = self.labels.get(self.company_var.get())
        if mode == 'manual' and cid is None:
            messagebox.showwarning('Párování firem','Vyberte celou společnost z našeptávače.',parent=self)
            return False
        try:
            self.links.save(row['source_name'],cid,mode,row['token'])
        except Exception as exc:
            messagebox.showwarning('Párování firem',str(exc),parent=self)
            return False
        self.reload(row['source_name'])
        return True

    def close(self):
        self.destroy()
        self.workspace.refresh_current()


class CompanyReportsUI:
    def open_company_links(self, customer=None):
        return CompanyLinkDialog(self,customer)

    def company_detail_bar(self, parent, customer):
        bar = ttk.Frame(parent,padding=(0,8)); bar.pack(fill='x')
        def refresh():
            for child in bar.winfo_children():child.destroy()
            row = self.company_links.resolve([customer])[customer]
            c = row['company']
            label = f"Adresář: {c['official_name']}" if c else 'Adresář: ' + row['status_text']
            ttk.Label(bar,text=label,wraplength=650).pack(side='left')
            ttk.Button(bar,text='Změnit přiřazení…',command=assign).pack(side='right')
            if c:
                ttk.Button(bar,text='Nabídky a objednávky z CRM…',
                    command=lambda:self.open_company_documents(c['id'])).pack(side='right',padx=8)
        def assign():
            dialog = self.open_company_links(customer)
            bar.wait_window(dialog)
            if bar.winfo_exists():refresh()
        refresh()

    def open_company_documents(self, company_id):
        companies = self.company_links.companies()
        cid = canonical_id(companies,company_id)
        if cid is None:
            messagebox.showwarning('Společnost','Společnost již není v adresáři.',parent=self)
            return
        c = companies[cid]
        win = tk.Toplevel(self); win.title(c['official_name'] + ' – doklady CRM')
        win.geometry('1100x650');win.minsize(820,500);win.transient(self.winfo_toplevel())
        outer = ttk.Frame(win,padding=16);outer.pack(fill='both',expand=True)
        ttk.Label(outer,text=c['official_name'],font=('Calibri',18,'bold')).pack(anchor='w')
        ttk.Label(outer,text=f"IČO: {c['ico'] or '—'}   •   {c['address'] or ''}",wraplength=1000).pack(anchor='w',pady=(4,8))
        aliases = [name for name, r in self.company_links.resolve().items() if r['company_id'] == cid]
        ttk.Label(outer,text='Názvy v importech: '+(', '.join(aliases) or '—'),wraplength=1000).pack(anchor='w')
        ttk.Label(outer,text='Doklady z CRM za všechna období. Obrat v měsíčních přehledech nadále vychází z importů POHODY.',
                  wraplength=1000).pack(anchor='w',pady=8)
        body = tk.Frame(outer,bg=COLORS['panel']);body.pack(fill='both',expand=True)
        tree = self._tree(body,('type','number','date','subject','status','net','currency','archived'),
            ('Typ dokladu','Číslo','Datum','Předmět','Stav','Bez DPH','Měna','Archiv'),
            (160,130,100,240,125,115,65,60),height=15,anchors=('w','w','w','w','w','e','w','w'))
        documents = {str(r['id']):r for r in self.company_links.documents(cid)}
        for iid, r in documents.items():
            tree.insert('','end',iid=iid,values=('Vydaná nabídka' if r['document_type']=='issued_offer' else 'Přijatá objednávka',
                r['document_number'],self.module.fmt_date(r['issue_date']),r['offer_subject'],r['status'],
                f"{r['subtotal_net'] or 0:,.2f}".replace(',',' '),r['currency'],'Ano' if r['archived'] else ''))
        app = self.winfo_toplevel()
        def open_selected(event=None):
            selected = tree.selection()
            r = documents.get(selected[0]) if selected else None
            if r is None:return
            method = 'open_issued_offer_editor' if r['document_type']=='issued_offer' else 'open_received_order_editor'
            callback = getattr(app,method,None)
            if callable(callback):
                win.destroy()
                callback(r['id'])
        tree.bind('<Double-1>',open_selected);tree.bind('<Return>',open_selected)
        ttk.Button(outer,text='Otevřít vybraný doklad',command=open_selected).pack(side='left',pady=(10,0))
        ttk.Button(outer,text='Zavřít',command=win.destroy).pack(side='right',pady=(10,0))
        return win
