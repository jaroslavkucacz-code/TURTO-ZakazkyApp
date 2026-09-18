"""Additional report pages and the import preview dialog."""
from pathlib import Path
import csv
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .constants import COLORS
from .management import monthly_comparison, customer_changes, project_results, coverage_rows
from .data_import import preview_imports, apply_imports


class ManagementUI:
    def _management_table(self,title,subtitle,headings,rows,widths,numeric=(),height=16):
        from .ui import Panel
        root=tk.Frame(self.container,bg=COLORS['bg']);root.pack(fill='both',expand=True)
        self.title_block(root,title,subtitle)
        panel=Panel(root,title);panel.pack(fill='both',expand=True)
        tree=self._tree(panel.body,tuple(f'c{i}' for i in range(len(headings))),headings,widths,height,
                        anchors=tuple('e' if i in numeric else 'w' for i in range(len(headings))))
        for values in rows:tree.insert('','end',values=values)
        return root,tree

    def page_monthly_comparison(self):
        from .ui import fmt_money,fmt_num,fmt_pct
        y,m=self.period();data=monthly_comparison(self.analytics,y,m,self.mode_key())
        self._management_table('Vývoj firmy','Měsíční výsledky a stejné měsíce předchozího roku. Pomlčka znamená chybějící podklad.',
            ('Období','Obrat','Obrat loni','Rozdíl Kč','Změna %','Dostupný zisk','Marže','Počet DL','Ø DL','Podklady'),
            [(r['period'],fmt_money(r['revenue']),fmt_money(r['previous_revenue']),fmt_money(r['change']),fmt_pct(r['change_percent']),
              fmt_money(r['profit']),fmt_pct(r['margin']),fmt_num(r['count']),fmt_money(r['average']),r['data_note']) for r in data],
            (90,125,125,120,95,135,90,85,115,170),numeric=tuple(range(1,9)))

    def page_customer_changes(self):
        from .ui import fmt_money,fmt_pct,fmt_num
        y,m=self.period();data=customer_changes(self.analytics,y,m,self.mode_key())
        _,tree=self._management_table('Změny zákazníků','Proti stejnému období loni, dle dostupných DL. První odběr znamená první záznam v této databázi.',
            ('Zákazník','Obrat','Obrat loni','Rozdíl Kč','Změna %','Počet DL','Stav'),
            [(r['customer'],fmt_money(r['revenue']),fmt_money(r['previous_revenue']),fmt_money(r['change']),fmt_pct(r['change_percent']),
              fmt_num(r['count']),r['state']) for r in data],(290,135,135,135,100,90,230),numeric=(1,2,3,4,5))
        def open_row(event):
            if tree.identify_region(event.x,event.y) not in ('cell','tree'):return
            item=tree.identify_row(event.y)
            if item:self.open_customer_detail(tree.item(item,'values')[0])
        tree.bind('<Double-1>',open_row)

    def page_projects(self):
        from .ui import fmt_money,fmt_pct,fmt_num
        y,m=self.period();data=project_results(self.analytics,y,m,self.mode_key())
        self._management_table('Zakázky','Souhrn podle označení zakázky v POHODĚ. Marže se zobrazí až po doplnění zisku ke všem DL zakázky.',
            ('Zakázka','Počet DL','Obrat','Dostupný zisk','Marže','DL se ziskem / celkem'),
            [(r['project'],fmt_num(r['documents']),fmt_money(r['revenue']),fmt_money(r['profit']),fmt_pct(r['margin']),r['coverage']) for r in data],
            (330,100,160,160,120,180),numeric=(1,2,3,4,5))

    def page_data_quality(self):
        from .ui import fmt_pct
        y,m=self.period();data=coverage_rows(self.analytics,y,m,self.mode_key())
        root,_=self._management_table('Kontrola dat','Navázání dostupných podkladů; počet záznamů sám o sobě nepotvrzuje úplnost měsíčního exportu.',
            ('Období','DL z POHODY','Chybí DL','DL se ziskem','Pokrytí zisku','Zdroj zisku','Položky s prodejem','Poslední datum','Co doplnit'),
            [(r['period'],r['delivery_documents'],r['missing_delivery'],r['profit_documents'],fmt_pct(r['coverage']),r['profit_source'],
              f"{r['priced']} / {r['items']}",r['latest_date'] or '—',r['status']) for r in data],
            (85,100,90,110,115,150,150,125,320),numeric=(1,2,3,4,6),height=13)
        tk.Button(root,text='Importovat další podklady…',command=self.do_import,bg=COLORS['teal'],fg='#06251D',
                  relief='flat',padx=16,pady=9).pack(anchor='w',pady=12)

    def import_templates(self,parent):
        frame=tk.Frame(parent,bg=COLORS['bg']);frame.pack(fill='x',pady=(0,12))
        tk.Label(frame,text='Další exporty CSV: ',bg=COLORS['bg'],fg=COLORS['muted']).pack(side='left')
        schemas={
            'Dodací listy':['Číslo','Datum','Kč základní','Celkem','Firma','Text','Středisko','Zakázka','Poznámka'],
            'Položky se ziskem':['Číslo DL','Datum','Firma','Kód','Název','Množství','Zisk celkem','Prodej celkem bez DPH','Náklad celkem bez DPH'],
            'Režijní listy':['Číslo','Datum','Splatno','Text','Firma','Celkem','K likvidaci','Středisko']}
        def save(name):
            filename={'Dodací listy':'DL','Položky se ziskem':'Polozky','Režijní listy':'Rezie'}[name]
            path=filedialog.asksaveasfilename(parent=self,initialfile='TURTO_import_'+filename+'.csv',defaultextension='.csv',filetypes=[('CSV','*.csv')])
            if not path:return
            try:
                with open(path,'w',encoding='utf-8-sig',newline='') as f:csv.writer(f,delimiter=';').writerow(schemas[name])
                messagebox.showinfo('Šablona importu','Šablona byla uložena.\n\nDatum: RRRR-MM-DD nebo DD.MM.RRRR. Částky bez DPH, desetinná čárka i tečka.\nPoložky stejného DL musí mít shodné datum a firmu. Prodej a náklad lze nechat prázdné, pokud je uveden zisk.\nSloupce můžete přeuspořádat, jejich názvy zachovejte.',parent=self)
            except Exception as exc:messagebox.showerror('Šablona',str(exc),parent=self)
        for name in schemas:
            tk.Button(frame,text='Šablona: '+name,command=lambda n=name:save(n),bg=COLORS['panel_soft'],fg=COLORS['text'],relief='flat',padx=10,pady=6).pack(side='left',padx=4)

    def _import_worker(self,title,fn,done):
        from queue import Queue,Empty
        from threading import Thread
        result=Queue();win=tk.Toplevel(self);win.title(title);win.configure(bg=COLORS['panel'])
        win.transient(self.winfo_toplevel());win.grab_set();win.protocol('WM_DELETE_WINDOW',lambda:None)
        tk.Label(win,text=title+'…',bg=COLORS['panel'],fg=COLORS['text'],font=('Calibri',13,'bold'),padx=28,pady=20).pack()
        bar=ttk.Progressbar(win,mode='indeterminate',length=330);bar.pack(padx=25,pady=(0,20));bar.start(12)
        def worker():
            try:result.put((True,fn()))
            except Exception as exc:result.put((False,str(exc)))
        def poll():
            try:ok,value=result.get_nowait()
            except Empty:self.after(100,poll);return
            bar.stop();win.grab_release();win.destroy()
            if ok:done(value)
            else:self._import_busy=False;messagebox.showerror('Import nebyl uložen',value,parent=self)
        Thread(target=worker,daemon=True,name='TURTO-import').start();self.after(100,poll)

    def start_import(self):
        if getattr(self,'_import_busy',False):return
        paths=filedialog.askopenfilenames(parent=self,title='Vyber exporty dat',filetypes=[('Excel / CSV','*.xlsx *.xlsm *.csv')])
        if not paths:return
        self._import_busy=True
        self._import_worker('Kontroluji vybrané soubory',lambda:preview_imports(self.db,paths),self._preview_dialog)

    def _preview_dialog(self,batch):
        from .ui import Panel
        win=tk.Toplevel(self);win.title('Kontrola před importem');win.geometry('1120x670');win.minsize(880,530)
        win.configure(bg=COLORS['bg']);win.transient(self.winfo_toplevel());win.grab_set()
        tk.Label(win,text='Kontrola před importem',font=('Calibri',20,'bold'),bg=COLORS['bg'],fg=COLORS['text']).pack(anchor='w',padx=20,pady=(16,5))
        tk.Label(win,text='Nové záznamy se doplní. Existující se změní pouze po zaškrtnutí volby dole. Každý soubor se archivuje.',
                 bg=COLORS['bg'],fg=COLORS['muted'],wraplength=1030,justify='left').pack(anchor='w',padx=20,pady=(0,10))
        p=Panel(win,'Rozpoznané podklady');p.pack(fill='both',expand=True,padx=20)
        tree=self._tree(p.body,('file','type','period','new','changed','same','state'),
                        ('Soubor','Typ dat','Období','Nové','Změněné','Shodné','Stav'),(240,150,160,65,85,70,145),8,('w','w','w','e','e','e','w'))
        for r in batch.summaries:
            tree.insert('','end',values=(r['file'],r['type'],r['period'],r['new'],r['changed'],r['same'],'Již načteno' if r['duplicate'] else 'Připraveno'))
        info=tk.Text(win,height=4,bg=COLORS['panel'],fg=COLORS['amber'],relief='flat',wrap='word',font=('Calibri',10))
        info.pack(fill='x',padx=20,pady=10)
        info.insert('1.0','\n'.join(batch.warnings) if batch.warnings else 'Kontrola neodhalila problém. Před uložením bude vytvořena záloha databáze.');info.configure(state='disabled')
        update=tk.BooleanVar(value=False)
        tk.Checkbutton(win,text='Aktualizovat také změněné existující doklady a souhrny (položky daného DL se nahradí)',
                       variable=update,bg=COLORS['bg'],fg=COLORS['text'],selectcolor=COLORS['panel'],activebackground=COLORS['bg'],activeforeground=COLORS['text']).pack(anchor='w',padx=20)
        footer=tk.Frame(win,bg=COLORS['bg']);footer.pack(fill='x',padx=20,pady=16)
        def cancel():self._import_busy=False;win.grab_release();win.destroy()
        def commit():
            replacing=update.get();win.grab_release();win.destroy()
            def finished(result):
                self._import_busy=False;self._populate_periods();self.refresh_current()
                detail=f"Uloženo záznamů: {result['changed']}\nPonecháno existujících: {result['skipped']}\nOpakované soubory: {result['duplicates']}"
                if result['backup']:detail+='\n\nZáloha:\n'+result['backup']
                messagebox.showinfo('Import dokončen',detail,parent=self)
            self._import_worker('Ukládám data a zálohu',lambda:apply_imports(self.db,batch,self.resolve_path(self.cfg['import_archive_dir']),
                                self.resolve_path(self.cfg['backup_dir']),replacing),finished)
        tk.Button(footer,text='Zrušit',command=cancel,bg=COLORS['panel_soft'],fg=COLORS['text'],relief='flat',padx=18,pady=9).pack(side='right',padx=6)
        tk.Button(footer,text='Uložit import',command=commit,bg=COLORS['teal'],fg='#06251D',relief='flat',padx=18,pady=9).pack(side='right')
        win.protocol('WM_DELETE_WINDOW',cancel);win.bind('<Escape>',lambda e:cancel())
