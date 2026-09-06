"""User-owned corporate PDF templates with measured preview and portable copies."""
from __future__ import annotations
import copy
import json
import tempfile
from pathlib import Path
from . import service, template_layout, template_bundle


def sample_offer():
    """Deliberately fictitious preview, never written to document/sequence tables."""
    doc=dict(document_number="UKÁZKA ŠABLONY",issue_date="2026-09-05",valid_to="2026-09-19",
        currency="CZK",offer_subject="Akustická izolace schodiště",project_name="Ukázková stavba",
        issuer_name_snapshot="TURTO s.r.o. – PRVKY DO ŽELEZOBETONU",
        issuer_address_snapshot="Kaprova 42/14, 110 00 Praha 1",issuer_ico_snapshot="24196231",issuer_dic_snapshot="CZ24196231",
        issuer_contact_snapshot="Obchodní oddělení",issuer_email_snapshot="info@turto.cz",
        customer_name_snapshot="Ukázkový odběratel s.r.o.",customer_address_snapshot="Ukázková 12, Praha",
        salesperson_snapshot="Obchodní oddělení",delivery_time="Dle dohody",delivery_address="Dle objednávky",
        payment_terms="Dle sjednaných podmínek",global_discount_pct=0,
        customer_note="Ukázková data slouží pouze pro posouzení vzhledu šablony.")
    rows=[]
    for n,(name,desc,qty,unit,price) in enumerate((
        ("Akustická kapsa – provedení A","Délka 130 cm; technické parametry dle specifikace.",102,"ks",1476),
        ("Akustická kapsa – provedení B","Délka 150 cm; technické parametry dle specifikace.",4,"ks",1716),
        ("Spárová deska","Šířka 360 mm; tloušťka 15 mm.",165,"m",350),
        ("Zvukově izolační deska","Šířka 500 mm; tloušťka 20 mm.",175,"m",163),
        ("Trn pro založení schodiště","Průměr 20 mm; s pouzdrem.",8,"ks",413)),1):
        rows.append(dict(row_type="product",name=name,description=desc,quantity=qty,unit=unit,
            unit_price=price,recommended_unit_price=price,discount_pct=0,vat_rate=21,
            category_name_snapshot="AKUSTICKÁ IZOLACE SCHODIŠŤ",subgroup_name_snapshot="Kapsy" if n<3 else "Doplňkové prvky",
            internal_code_snapshot=f"UK-{n:03d}"))
    return doc,rows


class TemplateEditor:
    def __init__(self,M,app,preview_document=None,preview_items=None):
        self.M,self.app=M,app
        self.preview_document=copy.deepcopy(preview_document) if preview_document is not None else None
        self.preview_items=copy.deepcopy(preview_items or [])
        self.win=M.tk.Toplevel(app);self.win._turto_template_editor=self;self.win.title("PDF šablony – TURTO CRM")
        self.win.transient(app)
        M.enable_dialog_maximize(self.win,1440,840)
        self.win.grab_set()
        self.selected=None;self.loaded={};self.loading=True;self.pending=None;self.preview_page=0
        self.preview_valid=False;self.preview_images=[];self.temp=tempfile.TemporaryDirectory(prefix="turto_template_")
        self.preview_target=Path(self.temp.name)/"preview.pdf"
        outer=M.ttk.Frame(self.win,padding=12);outer.pack(fill="both",expand=True)
        outer.columnconfigure(1,weight=1);outer.columnconfigure(2,weight=2);outer.rowconfigure(1,weight=1)
        M.ttk.Label(outer,text="PDF šablony vydaných nabídek",font=("Calibri",16,"bold")).grid(row=0,column=0,columnspan=3,sticky="w",pady=(0,10))
        left=M.ttk.Frame(outer,padding=(0,0,10,0));left.grid(row=1,column=0,sticky="ns")
        self.list=M.tk.Listbox(left,width=29,height=15,exportselection=False,font=("Calibri",10))
        self.list.pack(fill="both",expand=True)
        self.list.bind("<<ListboxSelect>>",self.select)
        for text,cmd in (("Nová firemní šablona",self.new),("Použít jako výchozí",self.make_default),("Export šablony…",self.export),("Import šablony…",self.import_), ("Deaktivovat",self.deactivate)):
            M.ttk.Button(left,text=text,command=cmd).pack(fill="x",pady=(6,0))
        form=M.ttk.Frame(outer,padding=(0,0,10,0));form.grid(row=1,column=1,sticky="nsew")
        form.columnconfigure(0,weight=1);form.rowconfigure(2,weight=1)
        self.name=M.tk.StringVar();M.ttk.Label(form,text="Název šablony").grid(row=0,column=0,sticky="w")
        M.ttk.Entry(form,textvariable=self.name).grid(row=1,column=0,sticky="ew",pady=(2,8))
        self.notebook=M.ttk.Notebook(form);self.notebook.grid(row=2,column=0,sticky="nsew")
        self.tabs={}
        for key,title in (("page","Stránka"),("type","Písmo"),("columns","Sloupce"),("blocks","Dolní bloky")):
            tab=M.ttk.Frame(self.notebook,padding=10);tab.columnconfigure(1,weight=1)
            self.notebook.add(tab,text=title);self.tabs[key]=tab
        self.vars={};self.layout_vars={}
        def entry(tab,row,label,key,value="",layout=False,file=False):
            var=M.tk.StringVar(value=str(value));(self.layout_vars if layout else self.vars)[key]=var
            M.ttk.Label(tab,text=label).grid(row=row,column=0,sticky="w",pady=4,padx=(0,6))
            e=M.ttk.Entry(tab,textvariable=var,width=16);e.grid(row=row,column=1,sticky="ew",pady=4)
            if file:
                def choose():
                    p=M.filedialog.askopenfilename(parent=self.win,filetypes=[("PNG, JPG nebo PDF","*.png *.jpg *.jpeg *.pdf")])
                    if p:
                        try: var.set(str(service.copy_template_asset(M,p,key)))
                        except Exception as exc: self.error(exc)
                M.ttk.Button(tab,text="…",width=3,command=choose).grid(row=row,column=2,padx=(4,0))
            return var
        def check(tab,row,label,key,layout=True):
            var=M.tk.BooleanVar();(self.layout_vars if layout else self.vars)[key]=var
            M.ttk.Checkbutton(tab,text=label,variable=var).grid(row=row,column=0,columnspan=3,sticky="w",pady=3)
        page=self.tabs["page"]
        for row,(key,label) in enumerate((("header_path","Záhlaví"),("footer_path","Zápatí"))):entry(page,row,label,key,file=True)
        specs=(("header_height_mm","Výška záhlaví [mm]"),("footer_height_mm","Výška zápatí [mm]"),
            ("margin_left_mm","Levý okraj [mm]"),("margin_right_mm","Pravý okraj [mm]"),
            ("body_top_gap_mm","Mezera pod záhlavím [mm]"),("body_bottom_gap_mm","Mezera nad zápatím [mm]"))
        for row,(key,label) in enumerate(specs,2):entry(page,row,label,key)
        check(page,8,"Záhlaví na každé stránce","header_every_page",False)
        check(page,9,"Zápatí na každé stránce","footer_every_page",False)
        check(page,10,"Aktivní šablona","active",False)
        M.ttk.Label(page,text="Grafika se nepřekresluje ani nepřebarvuje.\nPoměr stran loga zůstává zachovaný.",wraplength=320).grid(row=11,column=0,columnspan=3,sticky="w",pady=12)
        tab=self.tabs["type"]
        for row,(key,label) in enumerate((("title","Nadpis dokumentu"),("font_size","Velikost písma [pt]"),("row_padding_mm","Odsazení řádku [mm]"),("image_height_mm","Výška obrázku [mm]"),
            ("primary_color","Tmavá barva #RRGGBB"),("section_color","Barva oddílu #RRGGBB"),("subsection_color","Podklad pododdílu #RRGGBB"))):entry(tab,row,label,key,layout=True)
        check(tab,7,"Jemně střídat podklad řádků","zebra_rows")
        check(tab,8,"Zobrazit obrázky výrobků","show_images")
        check(tab,9,"Mezisoučty oddílů","show_group_subtotals")
        M.ttk.Label(tab,text="Na Windows se používá lokální Calibri; bez něj dostupné náhradní písmo.",wraplength=320).grid(row=10,column=0,columnspan=3,pady=10,sticky="w")
        self.build_columns()
        tab=self.tabs["blocks"]
        for row,(key,label) in enumerate((("closing_columns","Podmínky a kontakty vedle sebe"),("show_contacts","Zobrazit důležité kontakty"),("show_salesperson","Zobrazit vystavitele"),("show_vat_summary","Zobrazit také DPH a cenu s DPH"))):check(tab,row,label,key)
        self.texts={}
        for row,(key,label) in enumerate((("contacts_text","Důležité kontakty"),("closing_note","Závěrečná poznámka")),4):
            M.ttk.Label(tab,text=label).grid(row=2*row-4,column=0,columnspan=3,sticky="w",pady=(6,2))
            text=M.tk.Text(tab,height=4,width=32,font=("Calibri",10),wrap="word",undo=True)
            text.grid(row=2*row-3,column=0,columnspan=3,sticky="ew");self.texts[key]=text
            text.bind("<<Modified>>",self.text_changed)
        entry(tab,8,"Vlastní podpis / razítko","signature_path",layout=True,file=True)
        M.ttk.Label(tab,text="Ceny a podmínky konkrétní nabídky se mění v editoru nabídky. Toto je pouze vzhled a společné texty.",wraplength=320).grid(row=9,column=0,columnspan=3,sticky="w",pady=8)
        preview=M.ttk.Frame(outer);preview.grid(row=1,column=2,sticky="nsew")
        preview.columnconfigure(0,weight=1);preview.rowconfigure(1,weight=1)
        self.status=M.tk.StringVar()
        M.ttk.Label(preview,text="Náhled aktuální nabídky – bez uložení" if self.preview_document is not None else "Náhled šablony – ukázková data",font=("Calibri",11,"bold")).grid(row=0,column=0,sticky="w")
        self.canvas=M.tk.Canvas(preview,background="#E4E7E9",highlightthickness=0,width=420,height=600)
        self.canvas.grid(row=1,column=0,sticky="nsew",pady=5)
        self.canvas.bind("<Configure>",lambda e:self.schedule())
        navigation=M.ttk.Frame(preview);navigation.grid(row=2,column=0,sticky="ew")
        M.ttk.Button(navigation,text="‹",width=4,command=lambda:self.change_page(-1)).pack(side="left")
        M.ttk.Button(navigation,text="›",width=4,command=lambda:self.change_page(1)).pack(side="left")
        M.ttk.Button(navigation,text="Otevřít PDF",command=self.open_preview).pack(side="right")
        M.ttk.Label(preview,textvariable=self.status,wraplength=420).grid(row=3,column=0,sticky="w",pady=5)
        self.hint=M.tk.StringVar();M.ttk.Label(outer,textvariable=self.hint,wraplength=1100).grid(row=2,column=0,columnspan=3,sticky="w",pady=8)
        buttons=M.ttk.Frame(outer);buttons.grid(row=3,column=0,columnspan=3,sticky="ew")
        for text,cmd in (("Zavřít",self.close),("Uložit",self.save),("Uložit jako kopii…",lambda:self.save(True)),("Obnovit firemní vzhled",self.reset)):
            M.ttk.Button(buttons,text=text,command=cmd).pack(side="right",padx=4)
        M.ttk.Button(buttons,text="Nápověda",command=self.help).pack(side="left")
        for var in [self.name,*self.vars.values(),*self.layout_vars.values()]:var.trace_add("write",lambda *_:self.schedule())
        self.win.protocol("WM_DELETE_WINDOW",self.close)
        self.win.bind("<Escape>",lambda e:self.close())
        self.win.bind("<Control-s>",lambda e:self.save())
        self.win.bind("<F5>",lambda e:self.render_preview())
        self.win.bind("<F1>",lambda e:self.help())
        self.refresh_list();self.load(self.templates[0] if self.templates else template_layout.builtin_template())
        self.loading=False;self.schedule()

    def error(self,exc):self.M.messagebox.showwarning("PDF šablony",str(exc),parent=self.win)

    def build_columns(self):
        M=self.M;tab=self.tabs["columns"];tab.rowconfigure(0,weight=1)
        self.column_tree=M.ttk.Treeview(tab,columns=("label","width"),show="headings",height=9,selectmode="browse")
        self.column_tree.heading("label",text="Sloupec");self.column_tree.heading("width",text="Poměr")
        self.column_tree.column("label",width=200,anchor="w");self.column_tree.column("width",width=60,anchor="e")
        self.column_tree.grid(row=0,column=0,columnspan=3,sticky="nsew")
        self.col_label=M.tk.StringVar();self.col_width=M.tk.StringVar()
        for row,(label,var) in enumerate((("Popisek",self.col_label),("Poměrná šířka",self.col_width)),1):
            M.ttk.Label(tab,text=label).grid(row=row,column=0,sticky="w",pady=4)
            M.ttk.Entry(tab,textvariable=var).grid(row=row,column=1,columnspan=2,sticky="ew")
        bar=M.ttk.Frame(tab);bar.grid(row=3,column=0,columnspan=3,sticky="ew",pady=4)
        for text,cmd in (("Použít",self.apply_column),("Nahoru",lambda:self.move_column(-1)),("Dolů",lambda:self.move_column(1)),("Skrýt",self.remove_column)):
            M.ttk.Button(bar,text=text,command=cmd).pack(side="left",padx=2)
        self.add_var=M.tk.StringVar()
        self.add_combo=M.ttk.Combobox(tab,textvariable=self.add_var,values=[v[0] for v in template_layout.COLUMNS.values()],state="readonly")
        self.add_combo.grid(row=4,column=0,columnspan=2,sticky="ew",pady=5)
        M.ttk.Button(tab,text="Přidat",command=self.add_column).grid(row=4,column=2)
        M.ttk.Label(tab,text="Šířky jsou poměry, součet nemusí být 100. Změnu popisku/šířky potvrďte tlačítkem Použít. Množství se uvádí jen jednou.",wraplength=340).grid(row=5,column=0,columnspan=3,sticky="w",pady=8)
        self.column_tree.bind("<<TreeviewSelect>>",self.select_column)

    def column_index(self):
        sel=self.column_tree.selection()
        return int(sel[0]) if sel else None
    def refresh_columns(self,selected=None):
        self.column_tree.delete(*self.column_tree.get_children())
        for i,c in enumerate(self.columns):self.column_tree.insert("","end",iid=str(i),values=(c["label"],c["width"]))
        if selected is not None and 0<=selected<len(self.columns):self.column_tree.selection_set(str(selected))
        self.schedule()
    def select_column(self,*_):
        index=self.column_index()
        if index is not None:
            c=self.columns[index];self.col_label.set(c["label"]);self.col_width.set(str(c["width"]))
    def apply_column(self):
        index=self.column_index()
        if index is None:return
        try:
            width=template_layout._finite(self.col_width.get(),"Šířka",1,100)
            label=self.col_label.get().strip()
            if not label or len(label)>45:raise ValueError("Popisek musí mít 1 až 45 znaků.")
            self.columns[index].update(label=label,width=width);self.refresh_columns(index)
        except Exception as exc:self.error(exc)
    def move_column(self,delta):
        i=self.column_index()
        if i is not None and 0<=i+delta<len(self.columns):
            self.columns[i],self.columns[i+delta]=self.columns[i+delta],self.columns[i];self.refresh_columns(i+delta)
    def remove_column(self):
        i=self.column_index()
        if i is None:return
        if self.columns[i]["key"] in template_layout.REQUIRED:return self.error("Tento sloupec je povinný.")
        self.columns.pop(i);self.refresh_columns()
    def add_column(self):
        k=next((k for k,v in template_layout.COLUMNS.items() if v[0]==self.add_var.get()),None)
        if k and not any(c["key"]==k for c in self.columns):
            self.columns.append(dict(key=k,label=template_layout.COLUMNS[k][0],width=template_layout.COLUMNS[k][1]));self.refresh_columns(len(self.columns)-1)

    def raw_values(self):
        data={**self.loaded,"name":self.name.get(),**{k:v.get() for k,v in self.vars.items()}}
        if not self.legacy:
            layout={**self.layout,**{k:v.get() for k,v in self.layout_vars.items()},"columns":copy.deepcopy(self.columns)}
            layout.update({k:t.get("1.0","end-1c") for k,t in self.texts.items()})
            data["layout_json"]=json.dumps(layout,ensure_ascii=False,sort_keys=True)
        return data
    def values(self):
        data=self.raw_values()
        if not self.legacy:
            layout=template_layout.normalize(data["layout_json"])
            data=template_layout.validate_geometry(data,layout);data["layout_json"]=json.dumps(layout,ensure_ascii=False,sort_keys=True)
        return data
    def signature(self):return json.dumps(self.raw_values(),ensure_ascii=False,sort_keys=True,default=str)
    def discard_ok(self):
        return self.signature()==self.baseline or self.M.messagebox.askyesno("Neuložené změny","Zahodit rozpracované úpravy šablony?",parent=self.win)
    def load(self,data):
        self.loading=True;self.loaded=dict(data);self.selected=data.get("id");self.name.set(data.get("name",""))
        self.legacy=not template_layout.is_corporate(data)
        self.layout=template_layout.normalize(data.get("layout_json")) if not self.legacy else copy.deepcopy(template_layout.DEFAULT)
        self.columns=copy.deepcopy(self.layout["columns"])
        for k,v in self.vars.items():v.set(data.get(k,True if k in {"active","header_every_page","footer_every_page"} else ""))
        for k,v in self.layout_vars.items():v.set(self.layout[k])
        for k,t in self.texts.items():t.delete("1.0","end");t.insert("1.0",self.layout[k]);t.edit_modified(False)
        for key in ("type","columns","blocks"):self.notebook.tab(self.tabs[key],state="disabled" if self.legacy else "normal")
        self.refresh_columns();self.preview_page=0
        self.hint.set("Původní vzhled: geometrie zůstává upravitelná. Pro nový vzhled vytvořte firemní šablonu." if self.legacy else "Chráněná firemní předloha. Úpravy uložte jako vlastní kopii." if data.get("builtin_key") else "Vlastní šablona. Ukládá se do databáze a aktualizace programu ji nepřepisuje.")
        self.baseline=self.signature();self.loading=False;self.schedule()
    def refresh_list(self,selected=None):
        self.templates=service.list_templates(self.M,include_inactive=True)
        self.list.delete(0,"end")
        for i,t in enumerate(self.templates):
            self.list.insert("end",("★ " if t.get("is_default") else "")+t["name"]+(" [neaktivní]" if not t.get("active") else ""))
            if t["id"]==selected:self.list.selection_set(i)
    def select(self,*_):
        sel=self.list.curselection()
        if sel and self.templates[sel[0]]["id"]!=self.selected:
            if self.discard_ok():self.load(self.templates[sel[0]])
            else:self.refresh_list(self.selected)
    def new(self):
        if self.discard_ok():
            data=template_layout.builtin_template();data.pop("builtin_key",None);data["name"]="Moje firemní šablona";self.load(data)
    def reset(self):
        if not self.discard_ok():return
        name=self.name.get();selected=self.selected;loaded=dict(self.loaded)
        data=template_layout.builtin_template();data["name"]=name;data["id"]=selected;data["builtin_key"]=loaded.get("builtin_key","");data["is_default"]=loaded.get("is_default",0);data["active"]=loaded.get("active",1)
        previous=self.baseline;self.load(data);self.baseline=previous
    def save(self,copy_as=False):
        try:
            data=self.values();template_id=self.selected
            if not self.legacy and not self.render_preview():
                raise ValueError(self.status.get())
            if copy_as or data.get("builtin_key"):
                name=self.M.simpledialog.askstring("Kopie šablony","Název vlastní šablony:",initialvalue=self.name.get()+" – vlastní",parent=self.win)
                if name is None:return
                data["name"]=name;data["is_default"]=0;template_id=None
            data.pop("builtin_key",None)
            result=service.save_template(self.M,data,template_id)
            self.refresh_list(result);self.load(service.load_template(self.M,result))
            try:self.app.refresh_issued_offers()
            except Exception:pass
        except Exception as exc:self.error(exc)
    def make_default(self):
        if not self.selected or self.signature()!=self.baseline:return self.error("Nejdříve uložte šablonu.")
        try:
            service.set_default_template(self.M,self.selected)
            self.refresh_list(self.selected);self.load(service.load_template(self.M,self.selected))
        except Exception as exc:self.error(exc)
    def deactivate(self):
        if not self.selected:return
        if self.loaded.get("builtin_key"):return self.error("Firemní předlohu nelze odstranit. Vlastní kopie lze deaktivovat.")
        if not self.discard_ok():return
        if self.M.messagebox.askyesno("Šablony","Deaktivovat tuto šablonu? Starší nabídky a PDF zůstanou zachované.",parent=self.win):
            service.deactivate_template(self.M,self.selected);self.refresh_list();self.load(service.load_template(self.M,self.selected))
    def export(self):
        try:
            data=self.values()
            if self.legacy:raise ValueError("Přenosný export je určen pro nové firemní šablony.")
            path=self.M.filedialog.asksaveasfilename(parent=self.win,defaultextension=".zip",initialfile=service.safe_filename(data["name"])+".zip",filetypes=[("Šablona TURTO","*.zip")])
            if path:template_bundle.export_template(self.M,data,path)
        except Exception as exc:self.error(exc)
    def import_(self):
        if not self.discard_ok():return
        path=self.M.filedialog.askopenfilename(parent=self.win,filetypes=[("Šablona TURTO","*.zip")])
        if path:
            try:
                result=template_bundle.import_template(self.M,path);self.refresh_list(result);self.load(service.load_template(self.M,result))
            except Exception as exc:self.error(exc)
    def text_changed(self,event):
        if event.widget.edit_modified():event.widget.edit_modified(False);self.schedule()
    def schedule(self):
        if self.loading:return
        self.preview_valid=False
        if self.pending is not None:
            try:self.win.after_cancel(self.pending)
            except Exception:pass
        self.pending=self.win.after(400,self.render_preview)
    def render_preview(self):
        if self.pending is not None:
            try:self.win.after_cancel(self.pending)
            except Exception:pass
        self.pending=None
        self.preview_valid=False
        if self.legacy:
            self.canvas.delete("all");self.status.set("Původní šablona – pro nový náhled zvolte firemní vzhled.");return
        try:
            from . import pdf_renderer
            data=self.values()
            doc,items=(copy.deepcopy(self.preview_document),copy.deepcopy(self.preview_items)) if self.preview_document is not None else sample_offer()
            if not doc.get("document_number"): doc["document_number"]="NÁHLED NABÍDKY"
            pdf_renderer.render_offer_snapshot(self.M,doc,items,data,self.preview_target)
            self.show_page();self.preview_valid=True;self.status.set(f"Ukázka: strana {self.preview_page+1}/{self.page_count}. Změny nejsou uložené." if self.signature()!=self.baseline else f"Ukázka: strana {self.preview_page+1}/{self.page_count}.")
            return True
        except Exception as exc:
            self.status.set(str(exc));self.canvas.delete("all");self.preview_images=[]
            return False
    def show_page(self):
        import fitz
        from PIL import Image,ImageTk
        with fitz.open(self.preview_target) as pdf:
            self.page_count=pdf.page_count;self.preview_page=max(0,min(self.preview_page,self.page_count-1))
            page=pdf[self.preview_page]
            width=max(100,self.canvas.winfo_width()-20);height=max(100,self.canvas.winfo_height()-20)
            scale=min(width/page.rect.width,height/page.rect.height,2)
            pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
            photo=ImageTk.PhotoImage(Image.frombytes("RGB",(pix.width,pix.height),pix.samples),master=self.win)
        self.canvas.delete("all");self.preview_images=[photo]
        self.canvas.create_image(max(0,(self.canvas.winfo_width()-pix.width)/2),8,image=photo,anchor="nw")
    def change_page(self,delta):
        if self.preview_valid and self.preview_target.exists():self.preview_page+=delta;self.show_page();self.preview_valid=True;self.status.set(f"Ukázka: strana {self.preview_page+1}/{self.page_count}.")
    def open_preview(self):
        if self.render_preview() and self.preview_target.exists():service.open_path(self.preview_target)
    def help(self):
        from .professional_workflow import _open_help_topic
        _open_help_topic(self.M,self.win,"help_templates")
    def close(self):
        if not self.discard_ok():return
        if self.pending is not None:
            try:self.win.after_cancel(self.pending)
            except Exception:pass
        self.win.destroy();self.temp.cleanup()


def manage_templates(M,app,preview_document=None,preview_items=None):
    return TemplateEditor(M,app,preview_document,preview_items)


def install(M):
    M.App.manage_issued_offer_templates=lambda self:manage_templates(M,self)


__all__=["manage_templates","install","TemplateEditor"]
