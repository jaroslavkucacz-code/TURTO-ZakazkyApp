from __future__ import annotations

import os
import shutil
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkfont
from .ui_layout import PageViewport, responsive_grid
from pathlib import Path
from datetime import datetime

from .analytics import MONTH_NAMES
from .report_model import Analytics, selected_trend
from .charts import BusinessChart, ShareChart
from .config import load_config, save_config, resolve_path
from .constants import APP_NAME, APP_VERSION, COLORS, CENTER_NAMES, center_display
from .db import Database
from .exports import export_excel, export_pdf
from .management_ui import ManagementUI
from .updater import check_update, prepare_update, launch_installer


def fmt_money(v, decimals=0):
    if v is None:return '—'
    return (f'{v:,.{decimals}f} Kč').replace(',', ' ').replace('.', ',')

def fmt_num(v):
    try:
        n=float(v)
        txt=f'{n:,.2f}'.replace(',', ' ').replace('.', ',')
        return txt.rstrip('0').rstrip(',')
    except Exception:
        return str(v if v is not None else '—')

def fmt_pct(v):
    if v is None:return '—'
    return f'{v:.1f} %'.replace('.', ',')


class Card(tk.Frame):
    def __init__(self, master, title, value='—', subtitle='', accent=None, **kw):
        super().__init__(master, bg=COLORS['panel'], highlightbackground=COLORS['border'], highlightthickness=1, bd=0, **kw)
        self.configure(padx=16,pady=12)
        self.title_lbl=tk.Label(self,text=title,bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',10),anchor='w',justify='left');self.title_lbl.pack(fill='x')
        self.value_lbl=tk.Label(self,text=value,bg=COLORS['panel'],fg=COLORS['text'],font=('Calibri',18,'bold'))
        self.value_lbl.pack(anchor='w',pady=(6,2))
        self.sub_lbl=tk.Label(self,text=subtitle,bg=COLORS['panel'],fg=accent or COLORS['teal'],font=('Calibri',9))
        self.sub_lbl.configure(anchor='w',justify='left');self.sub_lbl.pack(fill='x')
        self._value_font=tkfont.Font(self,family='Calibri',size=18,weight='bold')
        self.value_lbl.configure(font=self._value_font)
        self.bind('<Configure>',self._fit_text,add='+')
    def _fit_text(self,event):
        width=max(35,event.width-36); text=self.value_lbl.cget('text')
        signature=(width,text)
        if getattr(self,'_fit_signature',None)==signature:return
        self._fit_signature=signature
        self.title_lbl.configure(wraplength=width);self.sub_lbl.configure(wraplength=width)
        probe=tkfont.Font(self,family='Calibri',size=18,weight='bold')
        size=18
        for size in (18,17,16,15,14,13,12):
            probe.configure(size=size)
            if probe.measure(text)<=width:break
        if int(self._value_font.cget('size'))!=size:self._value_font.configure(size=size)
    def set(self,value,subtitle='',accent=None):
        self.value_lbl.config(text=value)
        self.sub_lbl.config(text=subtitle,fg=accent or COLORS['teal'])


class Panel(tk.Frame):
    def __init__(self, master, title, **kw):
        super().__init__(master,bg=COLORS['panel'],highlightbackground=COLORS['border'],highlightthickness=1,bd=0,**kw)
        head=tk.Frame(self,bg=COLORS['panel']); head.pack(fill='x',padx=14,pady=(12,4))
        tk.Label(head,text=title,bg=COLORS['panel'],fg=COLORS['text'],font=('Calibri',12,'bold')).pack(side='left')
        self.body=tk.Frame(self,bg=COLORS['panel']); self.body.pack(fill='both',expand=True,padx=12,pady=(4,12))


class App(ManagementUI,tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg=load_config()
        for key in ('export_dir','import_archive_dir','backup_dir'):
            resolve_path(self.cfg[key]).mkdir(parents=True, exist_ok=True)
        self.db=Database(resolve_path(self.cfg['database_path']))
        self.analytics=Analytics(self.db)
        self.title(f'{APP_NAME}  {APP_VERSION}')
        self.geometry('1500x900'); self.minsize(1180,720); self.configure(bg=COLORS['bg'])
        self._apply_app_icon()
        try:
            self.state('zoomed')
        except Exception:
            pass
        self.option_add('*Font','Calibri 10')
        self._setup_ttk()
        self.pages={}; self.nav_buttons={}; self.current_page='Přehled'
        self._build_layout(); self._populate_periods(); self.show_page('Přehled'); self.after(1800,self._auto_check_updates)

    def _apply_app_icon(self):
        # Supply multiple sizes to Tk and a genuine multi-resolution ICO to
        # Windows. This keeps the title bar / Alt+Tab / taskbar crisp even at
        # different DPI scaling factors.
        assets=Path(__file__).resolve().parents[1] / 'assets'
        ico=assets / 'app_icon.ico'
        try:
            if ico.exists():
                self.iconbitmap(default=str(ico))
        except Exception:
            pass
        self._app_icon_images=[]
        try:
            for size in (16,20,24,32,40,48,64):
                p=assets / f'app_icon_{size}.png'
                if p.exists():
                    self._app_icon_images.append(tk.PhotoImage(file=str(p)))
            if self._app_icon_images:
                self.iconphoto(True,*self._app_icon_images)
        except Exception:
            pass
        try:
            from .windows_integration import install_native_icon_refresh
            install_native_icon_refresh(self,Path(__file__).resolve().parents[1])
        except Exception:
            pass
    def _setup_ttk(self):
        s=ttk.Style(self); s.theme_use('clam')
        s.configure('Dark.Treeview',background=COLORS['panel'],fieldbackground=COLORS['panel'],foreground=COLORS['text'],rowheight=28,borderwidth=0,font=('Calibri',10))
        s.configure('Dark.Treeview.Heading',background=COLORS['panel_soft'],foreground=COLORS['text'],font=('Calibri',10,'bold'),relief='flat',padding=(7,6))
        s.map('Dark.Treeview',background=[('selected',COLORS['panel_soft'])],foreground=[('selected',COLORS['text'])])

        # Readonly TCombobox uses its own state map on Windows. Without an explicit
        # map the OS theme can force a pale field while leaving the text white.
        s.configure('Dark.TCombobox',
                    fieldbackground=COLORS['panel_soft'],background=COLORS['panel_soft'],
                    foreground=COLORS['text'],arrowcolor=COLORS['text'],
                    bordercolor=COLORS['border'],lightcolor=COLORS['border'],
                    darkcolor=COLORS['border'],borderwidth=1,relief='flat',
                    padding=(9,6),font=('Calibri',11))
        s.map('Dark.TCombobox',
              fieldbackground=[('readonly',COLORS['panel_soft']),('focus',COLORS['panel_alt'])],
              background=[('readonly',COLORS['panel_soft']),('active',COLORS['panel_alt'])],
              foreground=[('readonly',COLORS['text']),('disabled',COLORS['muted'])],
              selectbackground=[('readonly',COLORS['panel_soft'])],
              selectforeground=[('readonly',COLORS['text'])],
              bordercolor=[('focus',COLORS['teal']),('readonly',COLORS['border'])],
              arrowcolor=[('readonly',COLORS['text']),('active',COLORS['teal'])])
        self.option_add('*TCombobox*Listbox.background', COLORS['panel_soft'])
        self.option_add('*TCombobox*Listbox.foreground', COLORS['text'])
        self.option_add('*TCombobox*Listbox.selectBackground', COLORS['teal'])
        self.option_add('*TCombobox*Listbox.selectForeground', '#06251D')
        self.option_add('*TCombobox*Listbox.font', 'Calibri 11')

    def _build_layout(self):
        self.sidebar=tk.Frame(self,bg='#0D1524',width=220); self.sidebar.pack(side='left',fill='y'); self.sidebar.pack_propagate(False)
        brand=tk.Frame(self.sidebar,bg='#0D1524'); brand.pack(fill='x',padx=14,pady=(20,20))
        icon_path=Path(__file__).resolve().parents[1] / 'assets' / 'app_icon_48.png'
        try:
            self._brand_icon=tk.PhotoImage(file=str(icon_path))
            tk.Label(brand,image=self._brand_icon,bg='#0D1524',bd=0).pack(side='left',padx=(0,10))
        except Exception:
            self._brand_icon=None
        brand_text=tk.Frame(brand,bg='#0D1524'); brand_text.pack(side='left',fill='x',expand=True)
        tk.Label(brand_text,text='TURTO',bg='#0D1524',fg=COLORS['text'],font=('Calibri',21,'bold')).pack(anchor='w')
        tk.Label(brand_text,text='MĚSÍČNÍ PŘEHLEDY',bg='#0D1524',fg=COLORS['muted'],font=('Calibri',8,'bold')).pack(anchor='w')
        for name in ['Přehled','Obrat & marže','Obchodníci','Zákazníci','Produkty','Vývoj firmy','Změny zákazníků','Zakázky','Kontrola dat','Importy','Nastavení']:
            b=tk.Button(self.sidebar,text=name,anchor='w',relief='flat',bd=0,bg='#0D1524',fg='#C7D2E0',activebackground=COLORS['panel_soft'],activeforeground=COLORS['text'],font=('Calibri',11),padx=20,pady=7,command=lambda n=name:self.show_page(n))
            b.pack(fill='x',padx=8,pady=2); self.nav_buttons[name]=b
        tk.Label(self.sidebar,text='Lepší data.\nSilnější rozhodnutí.',justify='left',bg='#0D1524',fg='#53657A',font=('Calibri',9)).pack(side='bottom',anchor='w',padx=20,pady=22)

        right=tk.Frame(self,bg=COLORS['bg']); right.pack(side='left',fill='both',expand=True)
        top=tk.Frame(right,bg=COLORS['bg'],height=92); top.pack(fill='x'); top.pack_propagate(False)
        left=tk.Frame(top,bg=COLORS['bg']); left.pack(side='left',fill='y',padx=22,pady=(10,8))

        period_box=tk.Frame(left,bg=COLORS['bg'])
        period_box.pack(side='left',fill='y',padx=(0,12))
        tk.Label(period_box,text='OBDOBÍ',bg=COLORS['bg'],fg='#B7C4D3',font=('Calibri',8,'bold')).pack(anchor='w',pady=(0,4))
        self.period_var=tk.StringVar(value=self.cfg.get('default_period','2026-08'))
        self.period_cb=ttk.Combobox(period_box,textvariable=self.period_var,width=12,state='readonly',style='Dark.TCombobox')
        self.period_cb.pack(anchor='w')
        self.period_cb.bind('<<ComboboxSelected>>',lambda e:self.refresh_current())

        mode_box=tk.Frame(left,bg=COLORS['bg'])
        mode_box.pack(side='left',fill='y',padx=(0,12))
        tk.Label(mode_box,text='ROZSAH',bg=COLORS['bg'],fg='#B7C4D3',font=('Calibri',8,'bold')).pack(anchor='w',pady=(0,4))
        self.mode_var=tk.StringVar(value='Měsíc')
        mode=ttk.Combobox(mode_box,textvariable=self.mode_var,values=['Měsíc','YTD','Rok','Posledních 12 měsíců'],width=20,state='readonly',style='Dark.TCombobox')
        mode.pack(anchor='w'); mode.bind('<<ComboboxSelected>>',lambda e:self.refresh_current())

        compare=tk.Frame(left,bg=COLORS['panel'],highlightbackground=COLORS['border'],highlightthickness=1,bd=0,padx=12,pady=7)
        compare.pack(side='left',anchor='s',pady=(18,0))
        tk.Label(compare,text='POROVNÁNÍ',bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',7,'bold')).pack(anchor='w')
        tk.Label(compare,text='Předchozí rok',bg=COLORS['panel'],fg=COLORS['text'],font=('Calibri',10,'bold')).pack(anchor='w',pady=(1,0))

        actions=tk.Frame(top,bg=COLORS['bg']); actions.pack(side='right',padx=22,pady=24)
        tk.Button(actions,text='Importovat data',command=self.do_import,bg=COLORS['teal'],fg='#06251D',activebackground=COLORS['teal2'],relief='flat',bd=0,font=('Calibri',10,'bold'),padx=16,pady=9).pack(side='left',padx=4)
        exp=tk.Menubutton(actions,text='Export',bg=COLORS['panel_soft'],fg=COLORS['text'],activebackground=COLORS['border'],activeforeground=COLORS['text'],relief='flat',bd=0,font=('Calibri',10,'bold'),padx=16,pady=9)
        menu=tk.Menu(exp,tearoff=0); menu.add_command(label='Excel – kompletní přehled',command=self.export_xlsx); menu.add_command(label='PDF – manažerský report',command=self.export_pdf); exp.config(menu=menu); exp.pack(side='left',padx=4)

        self.viewport=PageViewport(right);self.viewport.pack(fill='both',expand=True,padx=22,pady=(0,10));self.container=self.viewport.body
        statusbar=tk.Frame(right,bg=COLORS['bg']); statusbar.pack(fill='x',padx=22,pady=(0,7))
        self.status=tk.Label(statusbar,text='',anchor='w',bg=COLORS['bg'],fg=COLORS['muted'],font=('Calibri',8)); self.status.pack(side='left',fill='x',expand=True)
        tk.Label(statusbar,text='Vytvořil Ing. Jaroslav Kučera',anchor='e',bg=COLORS['bg'],fg='#607086',font=('Calibri',8)).pack(side='right')

    def _populate_periods(self):
        periods=self.analytics.available_periods()
        self.period_cb['values']=periods
        if self.period_var.get() not in periods and periods:
            self.period_var.set(periods[0])

    def mode_key(self):
        return {'Měsíc':'month','YTD':'ytd','Rok':'year','Posledních 12 měsíců':'rolling12'}.get(self.mode_var.get(),'month')
    def period(self):
        try: y,m=map(int,self.period_var.get().split('-')); return y,m
        except Exception: return 2026,8

    def show_page(self,name):
        for n,b in self.nav_buttons.items():
            b.config(bg=COLORS['panel_soft'] if n==name else '#0D1524',fg=COLORS['text'] if n==name else '#C7D2E0')
        for child in self.container.winfo_children(): child.destroy()
        self.viewport.canvas.yview_moveto(0)
        self.current_page=name
        maker={'Přehled':self.page_overview,'Obrat & marže':self.page_revenue,'Obchodníci':self.page_sales,'Zákazníci':self.page_customers,'Produkty':self.page_products,'Vývoj firmy':self.page_monthly_comparison,'Změny zákazníků':self.page_customer_changes,'Zakázky':self.page_projects,'Kontrola dat':self.page_data_quality,'Importy':self.page_imports,'Nastavení':self.page_settings}[name]
        try:
            maker()
        except Exception:
            log=Path(__file__).resolve().parents[1]/'turto_error.log'
            try: log.write_text(traceback.format_exc(),encoding='utf-8')
            except Exception: pass
            err=tk.Frame(self.container,bg=COLORS['bg']); err.pack(fill='both',expand=True,padx=24,pady=24)
            tk.Label(err,text='Tuto část se nepodařilo zobrazit.',bg=COLORS['bg'],fg=COLORS['red'],font=('Calibri',18,'bold')).pack(anchor='w')
            tk.Label(err,text='Program zůstal spuštěný. Podrobnosti jsou v turto_error.log.',bg=COLORS['bg'],fg=COLORS['muted'],font=('Calibri',10)).pack(anchor='w',pady=(6,0))
        self.update_status()

    def refresh_current(self): self.show_page(self.current_page)
    def title_block(self,parent,title,subtitle):
        f=tk.Frame(parent,bg=COLORS['bg']); f.pack(fill='x',pady=(4,16)); tk.Label(f,text=title,bg=COLORS['bg'],fg=COLORS['text'],font=('Calibri',22,'bold')).pack(anchor='w'); tk.Label(f,text=subtitle,bg=COLORS['bg'],fg=COLORS['muted'],font=('Calibri',10)).pack(anchor='w',pady=(3,0))

    def page_overview(self):
        root=tk.Frame(self.container,bg=COLORS['bg']); root.pack(fill='both',expand=True)
        self.title_block(root,'Přehled výkonnosti','Klíčové ukazatele za vybrané období')
        y,m=self.period(); mode=self.mode_key(); k=self.analytics.kpis(y,m,mode)
        cards=tk.Frame(root,bg=COLORS['bg']); cards.pack(fill='x')
        unassigned_note=(f"{k['unassigned_count']} nezařazených · {fmt_money(k['unassigned_revenue'])}" if k['unassigned_count'] else 'všechny doklady jsou přiřazené')
        vals=[('Obrat',fmt_money(k['revenue']),(f"{k['yoy']:+.1f} % vs. předchozí rok" if k.get('yoy_available') else 'srovnání není dostupné')),('Hrubý zisk',(fmt_money(k['profit'])+(' *' if not k['profit_complete'] else '')) if k['profit_available'] else '—','zisk z dostupných reportů'),('Průměrná marže',fmt_pct(k['margin']),'vážená marže'),('Počet DL',str(k['count']),unassigned_note),('Ø hodnota DL',fmt_money(k['avg_order']),'průměr na doklad'),('Režijní listy',fmt_money(k['overhead']),'za vybrané období')]
        for i,(a,b,c) in enumerate(vals):
            card=Card(cards,a,b,c,accent=COLORS['teal'] if not c.startswith('-') else COLORS['red']); card.grid(row=0,column=i,sticky='nsew',padx=(0 if i==0 else 6,0),ipady=2); cards.grid_columnconfigure(i,weight=1)
        responsive_grid(cards,cards.winfo_children(),6,3)
        mid=tk.Frame(root,bg=COLORS['bg']); mid.pack(fill='both',expand=True,pady=(14,0)); mid.grid_columnconfigure(0,weight=3); mid.grid_columnconfigure(1,weight=2); mid.grid_rowconfigure(0,weight=1)
        p=Panel(mid,'Obrat po měsících'); p.grid(row=0,column=0,sticky='nsew',padx=(0,7)); self.chart_trend(p.body,y)
        p3=Panel(mid,'Výkon obchodníků'); p3.grid(row=0,column=1,sticky='nsew',padx=(7,0)); self.sales_ranking(p3.body,self.analytics.salespeople(y,m,mode))
        responsive_grid(mid,[p,p3],2,1,threshold=1100)
        bot=tk.Frame(root,bg=COLORS['bg']); bot.pack(fill='both',expand=True,pady=(14,0)); bot.grid_columnconfigure(0,weight=2); bot.grid_columnconfigure(1,weight=1); bot.grid_columnconfigure(2,weight=1)
        cp=Panel(bot,'Top zákazníci'); cp.grid(row=0,column=0,sticky='nsew',padx=(0,7)); self.customer_table(cp.body,self.analytics.top_customers(y,m,mode,6),compact=True)
        pp=Panel(bot,'Produkty – nejvyšší zisk'); pp.grid(row=0,column=1,sticky='nsew',padx=7); self.product_compact(pp.body,self.analytics.products(y,m,5,mode))
        ip=Panel(bot,'Rychlý přehled'); ip.grid(row=0,column=2,sticky='nsew',padx=(7,0)); self.insights(ip.body,k,self.analytics.salespeople(y,m,mode))
        responsive_grid(bot,[cp,pp,ip],3,1)

    def _chart_options(self,key):
        preferences=self.cfg.get('chart_preferences',{})
        if not isinstance(preferences,dict):preferences={}
        return {'preferences':preferences.get(key,{}),'on_state_change':lambda state:self._save_chart_options(key,state)}

    def _save_chart_options(self,key,state):
        preferences=self.cfg.setdefault('chart_preferences',{})
        if not isinstance(preferences,dict):preferences={};self.cfg['chart_preferences']=preferences
        preferences[key]=state
        save_config(self.cfg)

    def chart_trend(self,parent,year):
        y,m=self.period()
        data=selected_trend(self.analytics,y,m,self.mode_key())
        trim_trailing=True
        chart=BusinessChart(
            parent,data,
            subtitle=('Vývoj od ledna do vybraného měsíce' if self.mode_key()=='month' else 'Vývoj vybraného období')+' · Kč vlevo / % vpravo',
            show_mode_switch=True,
            trim_trailing_empty=trim_trailing,
            on_period_click=self._on_trend_month_click,
            height=300,
            **self._chart_options('monthly'),
        )
        chart.pack(fill='both',expand=True)
        return chart

    def _on_trend_month_click(self,row):
        period=row.get('period')
        if period:
            self.period_var.set(period); self.mode_var.set('Měsíc'); self.show_page('Obrat & marže')


    def chart_margin(self,parent,margin):
        canvas=tk.Canvas(parent,bg=COLORS['panel'],highlightthickness=0,bd=0)
        canvas.pack(fill='both',expand=True)
        val=max(0.0,min(float(margin or 0),100.0))
        def draw(event=None):
            canvas.delete('all')
            w=max(canvas.winfo_width(),180); h=max(canvas.winfo_height(),180)
            size=max(80,min(w,h)-40); x0=(w-size)/2; y0=(h-size)/2; x1=x0+size; y1=y0+size
            ring=max(12,int(size*.11))
            canvas.create_arc(x0,y0,x1,y1,start=0,extent=359.9,style='arc',outline=COLORS['panel_soft'],width=ring)
            if val>0:
                canvas.create_arc(x0,y0,x1,y1,start=90,extent=-(359.9*val/100.0),style='arc',outline=COLORS['teal'],width=ring)
            canvas.create_text(w/2,h/2-4,text=f'{margin:.1f} %'.replace('.',','),fill=COLORS['text'],font=('Calibri',17,'bold'))
            canvas.create_text(w/2,h/2+22,text='vážená marže',fill=COLORS['muted'],font=('Calibri',8))
        canvas.bind('<Configure>',draw)
        parent.after_idle(draw)

    def sales_ranking(self,parent,rows):
        chart=ShareChart(parent,rows,metrics=(('profit','Zisk','money'),('revenue','Obrat','money'),('count','Počet DL','count')),
                         initial_metric='profit',max_items=6,height=245,**self._chart_options('sales'))
        chart.pack(fill='both',expand=True)
        return chart

    def _tree(self,parent,cols,headings,widths=None,height=8,anchors=None):
        # Jednotná tabulka s okamžitým vyhledáváním a řazením klikem na záhlaví.
        # Po opuštění záložky se tabulka znovu vytvoří, takže se řazení automaticky
        # vrátí do původního pořadí dat.
        search_bar=tk.Frame(parent,bg=COLORS['panel'])
        search_bar.pack(fill='x',pady=(0,7))
        tk.Label(search_bar,text='Hledat',bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',9)).pack(side='left',padx=(0,7))
        search_var=tk.StringVar()
        search_entry=tk.Entry(search_bar,textvariable=search_var,bg=COLORS['panel_soft'],fg=COLORS['text'],insertbackground=COLORS['text'],relief='flat',font=('Calibri',10))
        search_entry.pack(side='left',fill='x',expand=True,ipady=5)
        result_lbl=tk.Label(search_bar,text='',bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',8))
        result_lbl.pack(side='right',padx=(9,0))
        clear_btn=tk.Button(search_bar,text='×',command=lambda: search_var.set(''),bg=COLORS['panel_soft'],fg=COLORS['muted'],activebackground=COLORS['border'],activeforeground=COLORS['text'],relief='flat',bd=0,font=('Calibri',13,'bold'),width=2)
        clear_btn.pack(side='right',padx=(6,0))

        holder=tk.Frame(parent,bg=COLORS['panel'])
        holder.pack(fill='both',expand=True)
        tree=ttk.Treeview(holder,columns=cols,show='headings',height=height,style='Dark.Treeview')
        tree._heading_text={c:headings[i] for i,c in enumerate(cols)}
        tree._sort_col=None
        tree._sort_reverse=False
        for i,c in enumerate(cols):
            anchor=(anchors[i] if anchors else ('w' if i==0 else 'e'))
            tree.heading(c,text=headings[i],anchor=anchor)
            tree.column(c,width=(widths[i] if widths else 120),anchor=anchor,minwidth=45)
        scroll=ttk.Scrollbar(holder,orient='vertical',command=tree.yview)
        hscroll=ttk.Scrollbar(holder,orient='horizontal',command=tree.xview)
        tree.configure(yscrollcommand=scroll.set,xscrollcommand=hscroll.set)
        tree.grid(row=0,column=0,sticky='nsew'); scroll.grid(row=0,column=1,sticky='ns'); hscroll.grid(row=1,column=0,sticky='ew')
        holder.grid_rowconfigure(0,weight=1); holder.grid_columnconfigure(0,weight=1)

        original_insert=tree.insert
        tree._search_iids=[]
        def tracked_insert(parent_iid,index,**kw):
            iid=original_insert(parent_iid,index,**kw)
            if not parent_iid:
                tree._search_iids.append(iid)
                if search_var.get().strip() or tree._sort_col:
                    tree.after_idle(apply_filter)
                else:
                    result_lbl.config(text=f'{len(tree._search_iids)} řádků')
            return iid
        tree.insert=tracked_insert

        def normalize(value):
            return str(value if value is not None else '').lower().replace('\u00a0',' ').strip()

        def sort_value(value):
            # Přirozené řazení pro datumy, částky, procenta a počty; ostatní jako text.
            text=str(value if value is not None else '').strip()
            if not text or text in ('—','-'):
                return (3,'')
            # ISO datum / datum s časem
            import re
            m=re.match(r'^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?',text)
            if m:
                y=int(m.group(1)); mo=int(m.group(2)); d=int(m.group(3) or 1)
                return (0,y*10000+mo*100+d)
            m=re.match(r'^(\d{1,2})[.](\d{1,2})[.](\d{2,4})',text)
            if m:
                d=int(m.group(1)); mo=int(m.group(2)); y=int(m.group(3)); y += 2000 if y<100 else 0
                return (0,y*10000+mo*100+d)
            # Čísla, Kč, %, p.b., hvězdička u částečného zisku apod.
            cleaned=text.replace('Kč','').replace('%','').replace('*','').replace(' ','').replace('\u00a0','').replace(',','.').strip()
            if re.fullmatch(r'[-+]?\d+(?:\.\d+)?',cleaned):
                try: return (1,float(cleaned))
                except ValueError: pass
            return (2,normalize(text))

        def visible_iids():
            q=normalize(search_var.get())
            out=[]
            for iid in tree._search_iids:
                if not tree.exists(iid):continue
                vals=tree.item(iid,'values')
                hay=' | '.join(normalize(v) for v in vals)
                if not q or q in hay:
                    out.append(iid)
            return out

        def refresh_headings():
            for c in cols:
                label=tree._heading_text[c]
                if c==tree._sort_col:
                    label += '  ▼' if tree._sort_reverse else '  ▲'
                tree.heading(c,text=label)

        def sort_by_column(col):
            if tree._sort_col==col:
                tree._sort_reverse=not tree._sort_reverse
            else:
                tree._sort_col=col
                tree._sort_reverse=False
            refresh_headings()
            apply_filter()

        for c in cols:
            # default argument je nutný, aby každý handler držel svůj sloupec
            tree.heading(c,command=lambda column=c: sort_by_column(column))

        def apply_filter(*_):
            q=normalize(search_var.get())
            visible=visible_iids()
            if tree._sort_col:
                idx=cols.index(tree._sort_col)
                # Stabilní sort: při shodě zůstává původní pořadí z importu.
                order={iid:i for i,iid in enumerate(tree._search_iids)}
                missing=[iid for iid in visible if sort_value(tree.item(iid,'values')[idx])[0]==3]
                visible=[iid for iid in visible if iid not in set(missing)]
                visible.sort(key=lambda iid:sort_value(tree.item(iid,'values')[idx]),reverse=tree._sort_reverse)
                visible.extend(missing)
            # detach/reattach zachová data i vazby na dvojklik zákazníka.
            visible_set=set(visible)
            for iid in tree._search_iids:
                if tree.exists(iid) and iid not in visible_set:
                    tree.detach(iid)
            for iid in visible:
                tree.move(iid,'','end')
            total=len(tree._search_iids)
            result_lbl.config(text=(f'{len(visible)} / {total} řádků' if q else f'{total} řádků'))

        search_var.trace_add('write',apply_filter)
        tree.search_var=search_var
        tree.search_entry=search_entry
        tree.apply_filter=apply_filter
        tree.sort_by_column=sort_by_column
        return tree

    def customer_table(self,parent,rows,compact=False):
        if compact:
            tree=self._tree(parent,('customer','revenue','profit'),('Zákazník','Obrat','Zisk'),(210,115,105),height=6,anchors=('w','e','e'))
        else:
            tree=self._tree(parent,('customer','revenue','profit','margin','count'),('Zákazník','Obrat','Zisk','Marže','DL'),(360,145,135,95,75),height=18,anchors=('w','e','e','e','e'))
        item_customers={}
        for x in rows:
            rev=float(x.get('revenue') or 0); prof=float(x.get('profit') or 0); cnt=int(x.get('count') or 0); profit_docs=int(x.get('profit_docs',cnt) or 0)
            available=bool(x.get('profit_available',profit_docs>0)); complete=bool(x.get('profit_complete',cnt==0 or profit_docs>=cnt))
            margin=x.get('margin')
            profit_text=(fmt_money(prof)+(' *' if available and not complete else '')) if available else '—'
            margin_text=(fmt_pct(margin)+(' *' if available and not complete else '')) if margin is not None else '—'
            values=(x['customer'],fmt_money(rev),profit_text) if compact else (x['customer'],fmt_money(rev),profit_text,margin_text,cnt)
            iid=tree.insert('', 'end', values=values); item_customers[iid]=x['customer']
        def open_selected(event=None):
            iid=tree.focus()
            if not iid and tree.selection(): iid=tree.selection()[0]
            customer=item_customers.get(iid)
            if customer: self.open_customer_detail(customer)
        tree.bind('<Double-1>',open_selected); tree.bind('<Return>',open_selected)
        return tree

    def open_customer_detail(self,customer):
        history=self.analytics.customer_history(customer)
        if not history:
            messagebox.showinfo('Zákazník','Pro zákazníka nejsou dostupná historická data.')
            return
        win=tk.Toplevel(self); win.title(f'{customer} – historie'); win.geometry('1120x760'); win.minsize(900,650); win.configure(bg=COLORS['bg'])
        try: win.transient(self)
        except Exception: pass
        head=tk.Frame(win,bg=COLORS['bg']); head.pack(fill='x',padx=20,pady=(18,10))
        tk.Label(head,text=customer,bg=COLORS['bg'],fg=COLORS['text'],font=('Calibri',20,'bold')).pack(anchor='w')
        tk.Label(head,text='Historie podle dodacích listů z dostupných dat POHODA',bg=COLORS['bg'],fg=COLORS['muted'],font=('Calibri',9)).pack(anchor='w',pady=(2,0))
        total_rev=sum(x['revenue'] for x in history); total_count=sum(x['count'] for x in history)
        available=[x for x in history if x['profit_available']]; raw_profit=sum(x['profit'] for x in available)
        last=max((x.get('last_date') or '' for x in history),default='')
        cards=tk.Frame(win,bg=COLORS['bg']); cards.pack(fill='x',padx=20,pady=(0,12))
        vals=[('Obrat celkem',fmt_money(total_rev),'v celé dostupné historii'),('Počet DL',str(total_count),f'{len(history)} měsíců s odběrem'),('Zisk z dostupných reportů',fmt_money(raw_profit),f'zisková data: {len(available)} z {len(history)} měsíců'),('Poslední odběr',last if last else '—','datum posledního DL')]
        for i,(a,b,c) in enumerate(vals):
            Card(cards,a,b,c,accent=COLORS['amber'] if i==2 and len(available)<len(history) else COLORS['teal']).grid(row=0,column=i,sticky='nsew',padx=(0 if i==0 else 7,0)); cards.grid_columnconfigure(i,weight=1)
        chart=Panel(win,'Měsíční vývoj zákazníka'); chart.pack(fill='both',expand=True,padx=20,pady=(0,10)); self.chart_customer_history(chart.body,history)
        tab=Panel(win,'Historie po měsících'); tab.pack(fill='both',expand=True,padx=20,pady=(0,16))
        note=tk.Label(tab.body,text='Zisk a marže jsou zobrazeny pouze v měsících, pro které byl importován report Zisk (zásoby).',bg=COLORS['panel'],fg=COLORS['amber'],font=('Calibri',8),anchor='w')
        note.pack(fill='x',pady=(0,6))
        tree=self._tree(tab.body,('period','revenue','profit','margin','count'),('Období','Obrat','Zisk','Marže','DL'),(130,180,180,110,80),height=8,anchors=('w','e','e','e','e'))
        for x in reversed(history):
            suffix=' *' if x.get('profit_available') and not x.get('profit_complete',True) else ''
            profit_txt=(fmt_money(x['profit'])+suffix) if x['profit_available'] else '—'
            margin_txt=(fmt_pct(x['margin'])+suffix) if x['margin'] is not None else '—'
            tree.insert('', 'end',values=(x['period'],fmt_money(x['revenue']),profit_txt,margin_txt,x['count']))

    def chart_customer_history(self,parent,history):
        data=[]
        for x in history[-30:]:
            period=str(x.get('period') or '')
            label=(period[5:7]+'/'+period[2:4]) if len(period)>=7 else period
            revenue=float(x.get('revenue') or 0); profit=float(x.get('profit') or 0); available=bool(x.get('profit_available')); margin=x.get('margin') if available else None
            data.append({'label':label,'full_label':period,'revenue':revenue,'profit':profit,'margin':margin,'profit_available':available,'profit_complete':x.get('profit_complete',True),'has_data':True})
        chart=BusinessChart(parent,data,subtitle='Historie zákazníka • Kč vlevo / marže % vpravo',show_mode_switch=True,trim_trailing_empty=False,height=275,**self._chart_options('customer_history'))
        chart.pack(fill='both',expand=True); return chart

    def product_compact(self,parent,rows):
        for x in rows:
            f=tk.Frame(parent,bg=COLORS['panel']); f.pack(fill='x',pady=5); tk.Label(f,text=(x['code'] or '—')[:16],bg=COLORS['panel'],fg=COLORS['text'],font=('Calibri',9,'bold')).pack(side='left'); tk.Label(f,text=fmt_money(x['profit']),bg=COLORS['panel'],fg=COLORS['amber'],font=('Calibri',9)).pack(side='right')
        if not rows: tk.Label(parent,text='Pro toto období nejsou položková data.',bg=COLORS['panel'],fg=COLORS['muted']).pack(anchor='w')
    def insights(self,parent,k,sales):
        assigned=[x for x in sales if x.get('code')!='OTHER']
        best=assigned[0]['name'] if assigned else '—'
        texts=[f"Meziroční změna obratu: {k['yoy']:+.1f} %",f"Vážená marže: {fmt_pct(k['margin'])}",f"Nejvyšší obrat má {best}.",f"Nezařazené: {k['unassigned_count']} DL · {fmt_money(k['unassigned_revenue'])}",f"Režijní listy: {fmt_money(k['overhead'])}","Produktová % marže čeká na položkovou prodejní cenu."]
        for i,t in enumerate(texts):
            fg=COLORS['amber'] if i in (3,5) else COLORS['text']
            tk.Label(parent,text='• '+t,wraplength=260,justify='left',anchor='w',bg=COLORS['panel'],fg=fg,font=('Calibri',9)).pack(fill='x',pady=4)

    def page_revenue(self):
        root=tk.Frame(self.container,bg=COLORS['bg']); root.pack(fill='both',expand=True); self.title_block(root,'Obrat & marže','Měsíční vývoj, zisk a režijní listy')
        y,m=self.period(); p=Panel(root,'Vývoj vybraného období'); p.pack(fill='both',expand=True); self.chart_trend(p.body,y)
        table=Panel(root,'Měsíční souhrn'); table.pack(fill='both',expand=True,pady=(12,0)); tree=self._tree(table.body,('m','r','p','mar'),('Měsíc','Obrat','Zisk','Marže'),(140,170,170,100),12,anchors=('w','e','e','e'))
        for x in selected_trend(self.analytics,y,m,self.mode_key()): tree.insert('', 'end', values=(x.get('full_label',MONTH_NAMES[x['month']-1]),fmt_money(x['revenue']),fmt_money(x['profit']),fmt_pct(x['margin'])))

    def page_sales(self):
        root=tk.Frame(self.container,bg=COLORS['bg']); root.pack(fill='both',expand=True); self.title_block(root,'Obchodníci','Výkon středisek M / J / H včetně nezařazených dokladů')
        y,m=self.period(); mode=self.mode_key(); rows=self.analytics.salespeople(y,m,mode); ranked=sorted(rows,key=lambda x:x['profit'],reverse=True)
        chartp=Panel(root,'Podíly obchodníků a srovnání výkonu'); chartp.pack(fill='x')
        ShareChart(chartp.body,rows,metrics=(('profit','Zisk','money'),('revenue','Obrat','money'),('count','Počet DL','count')),initial_metric='profit',title_note='Zisk lze na úrovni obchodníků využít i ze starších měsíčních souhrnů.',max_items=6,height=245,**self._chart_options('sales')).pack(fill='both',expand=True)
        sp=Panel(root,'Souhrn výkonu obchodníků'); sp.pack(fill='x',pady=(12,0))
        tree=self._tree(sp.body,('name','revenue','profit','margin','count','avg','pshare'),('Obchodník','Obrat','Zisk','Marže','DL','Ø DL','Podíl na zisku'),(145,145,140,90,60,130,120),height=4,anchors=('w','e','e','e','e','e','e'))
        for x in ranked: tree.insert('', 'end',values=(x['name'],fmt_money(x['revenue']),((fmt_money(x['profit'])+(' *' if not x.get('profit_complete',True) else '')) if x.get('profit_available',True) else '—'),fmt_pct(x['margin']),x['count'],fmt_money(x['avg_order']),fmt_pct(x.get('profit_share',0))))
        p=Panel(root,'Největší doklady'); p.pack(fill='both',expand=True,pady=(12,0)); tree=self._tree(p.body,('center','doc','customer','project','amount','profit','margin'),('Středisko','DL','Zákazník','Projekt','Částka','Zisk','Marže'),(120,105,220,220,130,120,85),12,anchors=('w','w','w','w','e','e','e'))
        doc_map={}
        for x in self.analytics.top_documents(y,m,mode,limit=50):
            iid=tree.insert('', 'end',values=(center_display(x['center']),x['doc_no'],x['customer'],x['project'],fmt_money(x['base_amount']),fmt_money(x['profit']),fmt_pct(x['margin']))); doc_map[iid]=x['doc_no']
        def open_doc(event=None):
            if event is not None and getattr(event,'keysym','') != 'Return' and tree.identify_region(event.x,event.y) != 'cell':return
            iid=tree.identify_row(event.y) if event is not None and getattr(event,'keysym','') != 'Return' else tree.focus()
            if not iid and tree.selection(): iid=tree.selection()[0]
            doc_no=doc_map.get(iid)
            if doc_no: self.open_document_detail(doc_no)
        tree.bind('<Double-1>',open_doc); tree.bind('<Return>',open_doc)
        tk.Label(p.body,text='Dvojklikem na řádek otevřete položky dodacího listu.',bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',8),anchor='w').pack(fill='x',pady=(6,0))

    def open_document_detail(self,doc_no):
        data=self.analytics.document_detail(doc_no)
        if not data:
            messagebox.showinfo('Dodací list','Dodací list se nepodařilo najít v databázi.')
            return
        win=tk.Toplevel(self); win.title(f"{doc_no} – položky dodacího listu"); win.geometry('1380x780'); win.minsize(1050,650); win.configure(bg=COLORS['bg'])
        try: win.transient(self)
        except Exception: pass
        head=tk.Frame(win,bg=COLORS['bg']); head.pack(fill='x',padx=20,pady=(18,8))
        tk.Label(head,text=f"Dodací list {doc_no}",bg=COLORS['bg'],fg=COLORS['text'],font=('Calibri',20,'bold')).pack(anchor='w')
        subtitle=f"{data.get('customer') or '—'} · {data.get('doc_date') or '—'} · {center_display(data.get('center'))}"
        tk.Label(head,text=subtitle,bg=COLORS['bg'],fg=COLORS['muted'],font=('Calibri',10)).pack(anchor='w',pady=(2,0))
        if data.get('description'):
            tk.Label(head,text=data.get('description'),bg=COLORS['bg'],fg=COLORS['text'],font=('Calibri',10),anchor='w').pack(anchor='w',pady=(5,0))

        cards=tk.Frame(win,bg=COLORS['bg']); cards.pack(fill='x',padx=20,pady=(0,12))
        profit_available=bool(data.get('profit_available')); margin=data.get('margin_percent')
        vals=[
            ('Částka bez DPH',fmt_money(data.get('base_amount') or 0),'hodnota DL'),
            ('Zisk',fmt_money(data.get('profit_total') or 0) if profit_available else '—','z reportu Zisk (zásoby)' if profit_available else 'ziskový report chybí'),
            ('Marže',fmt_pct(margin) if margin is not None else '—','marže celého DL'),
            ('Položek',str(len(data.get('items') or [])),'položkových řádků')
        ]
        for i,(a,b,c) in enumerate(vals):
            Card(cards,a,b,c,accent=COLORS['amber'] if i in (1,2) else COLORS['teal']).grid(row=0,column=i,sticky='nsew',padx=(0 if i==0 else 7,0)); cards.grid_columnconfigure(i,weight=1)

        panel=Panel(win,'Položky dodacího listu'); panel.pack(fill='both',expand=True,padx=20,pady=(0,16))
        tk.Label(panel.body,text='Prodejní cena, náklad a položková marže jsou připravené pro budoucí export z POHODY. Pokud je zdroj zatím neobsahuje, zobrazí se —.',bg=COLORS['panel'],fg=COLORS['amber'],font=('Calibri',8),anchor='w').pack(fill='x',pady=(0,6))
        tree=self._tree(panel.body,('code','name','item_text','qty','sales','cost','profit_unit','profit','margin'),('Kód','Název','Poznámka / balení','Množství','Prodej','Náklad','Zisk / j.','Zisk','Marže'),(160,330,190,90,115,115,105,115,85),height=16,anchors=('w','w','w','e','e','e','e','e','e'))
        def maybe_money(v): return fmt_money(v) if v is not None else '—'
        def maybe_pct(v): return fmt_pct(v) if v is not None else '—'
        items=data.get('items') or []
        for item in items:
            tree.insert('', 'end',values=(
                item.get('code') or '—',item.get('name') or '—',item.get('item_text') or '',fmt_num(item.get('quantity') or 0),
                maybe_money(item.get('sales_total')),maybe_money(item.get('cost_total')),fmt_money(item.get('profit_unit') or 0,2),fmt_money(item.get('profit_total') or 0),maybe_pct(item.get('margin_percent'))))
        if not items:
            tk.Label(panel.body,text='Pro tento dodací list nejsou položková data z reportu Zisk (zásoby) dostupná.',bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',10)).pack(anchor='w',pady=10)

    def page_customers(self):
        root=tk.Frame(self.container,bg=COLORS['bg']); root.pack(fill='both',expand=True); self.title_block(root,'Zákazníci','Podíly odběratelů • kliknutím na zákazníka v grafu otevřete jeho historii')
        y,m=self.period(); mode=self.mode_key(); rows=self.analytics.top_customers(y,m,mode,-1)
        chart_rows=[]
        for x in rows:
            q=dict(x); q['label']=q.get('customer','—'); q['profit']=q['profit'] if q.get('profit_available') else None; chart_rows.append(q)
        cp=Panel(root,'Zastoupení zákazníků'); cp.pack(fill='x')
        ShareChart(cp.body,chart_rows,metrics=(('profit','Zisk','money'),('revenue','Obrat','money'),('count','Počet DL','count')),initial_metric='revenue',title_note='TOP 6 + ostatní z celého období. Zisk pouze ze spárovaných DL. Záporné hodnoty jsou dostupné v pruzích.',max_items=6,on_item_click=lambda r:self.open_customer_detail(r.get('customer')) if r.get('customer') else None,height=255,**self._chart_options('customers')).pack(fill='both',expand=True)
        p=Panel(root,'Všichni zákazníci za vybrané období'); p.pack(fill='both',expand=True,pady=(12,0)); self.customer_table(p.body,rows,compact=False)

    def page_products(self):
        root=tk.Frame(self.container,bg=COLORS['bg']); root.pack(fill='both',expand=True); self.title_block(root,'Produkty','Položkový zisk a dostupný obrat ve stejném období jako zbytek přehledu')
        y,m=self.period(); mode=self.mode_key(); rows=self.analytics.products(y,m,-1,mode); coverage=self.analytics.item_data_coverage(y,m,mode)
        chart_rows=[]
        for x in rows:
            q=dict(x); q['label']=((q.get('code') or '')+' – '+(q.get('name') or '')).strip(' –'); q['revenue']=q.get('sales'); q['count']=q.get('documents'); chart_rows.append(q)
        note=f"Položková data: {coverage['item_docs']} z {coverage['total_docs']} DL. Obrat produktu vyžaduje položkovou prodejní hodnotu. Stejný DL se může započítat u více produktů."
        cp=Panel(root,'Zastoupení produktů'); cp.pack(fill='x')
        ShareChart(cp.body,chart_rows,metrics=(('profit','Zisk','money'),('revenue','Obrat','money'),('count','Počet DL','count')),initial_metric='profit',title_note=note,max_items=6,exclude_negative_from_shares=True,height=255,**self._chart_options('products')).pack(fill='both',expand=True)
        p=Panel(root,'Produkty za vybrané období'); p.pack(fill='both',expand=True,pady=(12,0)); tree=self._tree(p.body,('code','name','qty','profit','sales','margin','docs'),('Kód','Produkt','Množství','Zisk','Dostupný obrat','Marže','DL'),(155,410,100,130,130,90,65),20,anchors=('w','w','e','e','e','e','e'))
        for x in rows:
            sales=fmt_money(x['sales']) if x.get('sales') is not None else '—'; margin=fmt_pct(x['margin']) if x.get('margin') is not None else '—'
            tree.insert('', 'end',values=(x['code'],x['name'],fmt_num(x['quantity']),fmt_money(x['profit']),sales,margin,x['documents']))

    def page_imports(self):
        root=tk.Frame(self.container,bg=COLORS['bg']); root.pack(fill='both',expand=True); self.title_block(root,'Importy','Historie načtených dat a kontrola zdrojů')
        bar=tk.Frame(root,bg=COLORS['bg']); bar.pack(fill='x',pady=(0,10)); tk.Button(bar,text='Importovat Excel / CSV',command=self.do_import,bg=COLORS['teal'],fg='#06251D',relief='flat',padx=14,pady=8,font=('Calibri',10,'bold')).pack(side='left'); tk.Label(bar,text='Podporováno: DATA POHODA, režijní listy, Zisk (zásoby), historický list ZISKY',bg=COLORS['bg'],fg=COLORS['muted']).pack(side='left',padx=14)
        self.import_templates(root)
        p=Panel(root,'Historie importů'); p.pack(fill='both',expand=True); tree=self._tree(p.body,('date','type','file','period','rows','status','notes'),('Datum','Typ','Soubor','Období','Řádky','Stav','Podrobnosti'),(145,160,300,100,80,100,420),16,anchors=('w','w','w','c','e','c','w'))
        rows=self.db.query('SELECT * FROM imports ORDER BY id DESC LIMIT 300')
        for x in rows: tree.insert('', 'end',values=(x['imported_at'].replace('T',' '),x['import_type'],x['file_name'],f"{x['period_year'] or ''}-{x['period_month']:02d}" if x['period_month'] else '',x['row_count'],x['status'],x['notes']))

    def page_settings(self):
        root=tk.Frame(self.container,bg=COLORS['bg']); root.pack(fill='both',expand=True); self.title_block(root,'Nastavení','Databáze, zálohy a online aktualizace')
        p=Panel(root,'Databáze'); p.pack(fill='x'); dbp=str(resolve_path(self.cfg['database_path'])); tk.Label(p.body,text='Aktuální databáze',bg=COLORS['panel'],fg=COLORS['muted']).grid(row=0,column=0,sticky='w'); e=tk.Entry(p.body,bg=COLORS['panel_soft'],fg=COLORS['text'],insertbackground=COLORS['text'],relief='flat'); e.insert(0,dbp); e.config(state='readonly'); e.grid(row=1,column=0,sticky='ew',pady=(4,8),ipady=6); p.body.grid_columnconfigure(0,weight=1)
        tk.Button(p.body,text='Přesunout / zvolit sdílenou databázi…',command=self.change_db,bg=COLORS['panel_soft'],fg=COLORS['text'],relief='flat',padx=12,pady=7).grid(row=1,column=1,padx=8)
        tk.Button(p.body,text='Vytvořit zálohu',command=self.make_backup,bg=COLORS['panel_soft'],fg=COLORS['text'],relief='flat',padx=12,pady=7).grid(row=1,column=2)
        launch=Panel(root,'Spouštění programu');launch.pack(fill='x',pady=(12,0))
        from .config import app_root
        import sys
        executable=str(Path(sys.executable).resolve()) if getattr(sys,'frozen',False) else str(app_root()/'app.pyw')
        tk.Label(launch.body,text=f'Právě spuštěná verze: {APP_VERSION}',bg=COLORS['panel'],fg=COLORS['text'],font=('Calibri',10,'bold')).pack(anchor='w')
        location=tk.Entry(launch.body,relief='flat',readonlybackground=COLORS['panel_soft'],fg=COLORS['text'])
        location.insert(0,executable);location.configure(state='readonly');location.pack(fill='x',pady=(5,8),ipady=5)
        actions=tk.Frame(launch.body,bg=COLORS['panel']);actions.pack(fill='x')
        tk.Button(actions,text='Otevřít složku programu',command=lambda:os.startfile(str(app_root())),bg=COLORS['panel_soft'],fg=COLORS['text'],relief='flat',padx=12,pady=7).pack(side='left')
        tk.Button(actions,text='Opravit zástupce Windows',command=self.repair_launch_shortcuts,bg=COLORS['teal'],fg='#06251D',relief='flat',padx=12,pady=7).pack(side='left',padx=8)
        up=Panel(root,'Online aktualizace'); up.pack(fill='x',pady=(12,0))
        update_url=self.cfg.get('update_manifest_url','').strip()
        state_text='Aktivní – GitHub aktualizační kanál je připojen' if update_url else 'Aktualizační kanál není dostupný'
        state_color=COLORS['teal'] if update_url else COLORS['amber']
        tk.Label(up.body,text=f'Aktuální verze: {APP_VERSION}',bg=COLORS['panel'],fg=COLORS['text'],font=('Calibri',10,'bold')).grid(row=0,column=0,sticky='w')
        tk.Label(up.body,text=state_text,bg=COLORS['panel'],fg=state_color,font=('Calibri',9,'bold')).grid(row=0,column=1,sticky='e')
        tk.Label(up.body,text='Kanál: TURTO-Mesicni-Prehledy · stabilní',bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',9)).grid(row=1,column=0,sticky='w',pady=(8,0))
        tk.Label(up.body,text='Kontrola probíhá automaticky po spuštění programu.',bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',9)).grid(row=2,column=0,sticky='w',pady=(2,0))
        up.body.grid_columnconfigure(0,weight=1)
        tk.Button(up.body,text='Zkontrolovat aktualizace',command=self.check_updates,bg=COLORS['teal'],fg='#06251D',relief='flat',padx=14,pady=8,font=('Calibri',10,'bold')).grid(row=1,column=1,rowspan=2,padx=(14,0),sticky='e')
        info=Panel(root,'O programu'); info.pack(fill='x',pady=(12,0)); tk.Label(info.body,text='TURTO – Měsíční přehledy\nVytvořil Ing. Jaroslav Kučera\nDatová vrstva je oddělená od UI a připravená pro pozdější centrální databázi.',justify='left',bg=COLORS['panel'],fg=COLORS['muted']).pack(anchor='w')

    def do_import(self):
        self.start_import()

    def export_xlsx(self):
        y,m=self.period(); default=f'TURTO_prehled_{y}_{m:02d}.xlsx'; path=filedialog.asksaveasfilename(defaultextension='.xlsx',initialdir=str(resolve_path(self.cfg['export_dir'])),initialfile=default,filetypes=[('Excel','*.xlsx')]);
        if not path:return
        try: export_excel(path,self.analytics,y,m,self.mode_key()); messagebox.showinfo('Export','Excel byl vytvořen:\n'+path)
        except Exception as e: messagebox.showerror('Export se nezdařil',str(e))
    def export_pdf(self):
        if getattr(self,'_pdf_busy',False):
            messagebox.showinfo('PDF report','Předchozí report se ještě připravuje.',parent=self)
            return
        y,m=self.period(); mode=self.mode_key()
        path=filedialog.asksaveasfilename(defaultextension='.pdf',initialdir=str(resolve_path(self.cfg['export_dir'])),initialfile=f'TURTO_report_{y}_{m:02d}_{mode}.pdf',filetypes=[('PDF','*.pdf')])
        if not path:return
        from queue import Queue, Empty
        from threading import Thread
        result=Queue(); self._pdf_busy=True
        progress=tk.Toplevel(self); progress.title('Export PDF'); progress.configure(bg=COLORS['panel']); progress.resizable(False,False)
        progress.transient(self)
        tk.Label(progress,text='Připravuji podrobný PDF report…',bg=COLORS['panel'],fg=COLORS['text'],font=('Calibri',12,'bold'),padx=24,pady=18).pack()
        tk.Label(progress,text='Grafy, tabulky a kontrola dostupnosti dat.\nProgram můžete dál používat.',bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',10),padx=24,pady=12).pack()
        progress.protocol('WM_DELETE_WINDOW',progress.withdraw)
        def worker():
            try:
                export_pdf(path,self.analytics,y,m,mode); result.put((True,path))
            except Exception as exc:result.put((False,str(exc)))
        def poll():
            try:ok,text=result.get_nowait()
            except Empty:
                self.after(120,poll); return
            self._pdf_busy=False
            if progress.winfo_exists():progress.destroy()
            if ok:messagebox.showinfo('Export','PDF report byl vytvořen:\n'+text,parent=self)
            else:messagebox.showerror('Export se nezdařil',text,parent=self)
        Thread(target=worker,daemon=True,name='TURTO-PDF').start();self.after(120,poll)

    def repair_launch_shortcuts(self):
        from .windows_shell import repair_current_user
        try:
            result=repair_current_user(force=True)
            if result.get('errors'):
                details='\n'.join(x.get('error','') for x in result['errors'])
                messagebox.showwarning('Oprava zástupců','Některé zástupce se nepodařilo opravit:\n'+details,parent=self)
            else:
                text=f"Zástupce směřují na verzi {APP_VERSION}.\n\n{result['target']}"
                text+='\n\nPokud připnutá ikona stále spouští starou verzi, jednou ji odepněte a znovu připněte aktuální spuštěný program.'
                if result.get('backup'):text+='\n\nZáloha původních zástupců:\n'+result['backup']
                messagebox.showinfo('Oprava zástupců',text,parent=self)
        except Exception as exc:messagebox.showerror('Oprava zástupců',str(exc),parent=self)

    def change_db(self):
        path=filedialog.asksaveasfilename(title='Umístění společné databáze',defaultextension='.db',filetypes=[('SQLite databáze','*.db')]);
        if not path:return
        try:
            new=Path(path); new.parent.mkdir(parents=True,exist_ok=True)
            if not new.exists(): shutil.copy2(self.db.path,new)
            self.cfg['database_path']=str(new); save_config(self.cfg); messagebox.showinfo('Databáze','Nové umístění bylo uloženo. Program nyní ukončete a spusťte znovu.')
        except Exception as e: messagebox.showerror('Databáze',str(e))
    def make_backup(self):
        try: p=self.db.backup(resolve_path(self.cfg['backup_dir'])); messagebox.showinfo('Záloha','Záloha vytvořena:\n'+str(p))
        except Exception as e: messagebox.showerror('Záloha',str(e))
    def check_updates(self):
        try:
            r=check_update(self.cfg.get('update_manifest_url','').strip())
            if not r.get('configured'): messagebox.showinfo('Aktualizace','Online aktualizační kanál není dostupný.')
            elif r.get('available'):
                text=f"K dispozici je verze {r['latest']}.\n\n{r.get('notes','')}\n\nChcete ji stáhnout a nainstalovat? Databáze, importy, exporty a lokální nastavení zůstanou zachované."
                if r.get('url') and messagebox.askyesno('Aktualizace', text):
                    package=prepare_update(r['url'], r.get('sha256',''))
                    launch_installer(package)
                    self.destroy()
                elif not r.get('url'):
                    messagebox.showinfo('Aktualizace', text+'\n\nManifest neobsahuje URL balíčku.')
            else: messagebox.showinfo('Aktualizace',f"Verze je aktuální.\n\nPoužíváte nejnovější verzi {r.get('current',APP_VERSION)}.")
        except Exception as e: messagebox.showerror('Aktualizace',str(e))
    def _auto_check_updates(self):
        url=self.cfg.get('update_manifest_url','').strip()
        if not url:
            return
        try:
            r=check_update(url)
            if r.get('available') and r.get('url'):
                text=f"Je dostupná nová verze {r['latest']}.\n\n{r.get('notes','')}\n\nChcete ji nyní stáhnout a nainstalovat?"
                if messagebox.askyesno('Dostupná aktualizace',text):
                    package=prepare_update(r['url'],r.get('sha256',''))
                    launch_installer(package)
                    self.destroy()
        except Exception:
            # Automatická kontrola nesmí bránit spuštění programu; ruční kontrola
            # v Nastavení zobrazí podrobnou chybu.
            pass

    def update_status(self):
        last=self.db.query('SELECT imported_at,file_name FROM imports ORDER BY id DESC LIMIT 1'); txt=f'Databáze: {self.db.path}'
        if last: txt+=f"   •   Poslední import: {last[0]['imported_at'].replace('T',' ')} – {last[0]['file_name']}"
        self.status.config(text=txt)
