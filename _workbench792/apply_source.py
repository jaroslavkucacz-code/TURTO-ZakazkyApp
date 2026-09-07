from pathlib import Path
root=Path.cwd();src=root/'ZakazkyApp_base_6.1';offer=src/'price_lists_domain/issued_offers'
def change(path,old,new,n=1):
    text=path.read_text(encoding='utf-8');assert text.count(old)==n,(path.name,text.count(old),old[:80]);path.write_text(text.replace(old,new),encoding='utf-8')
p=offer/'service.py'
change(p,'    return document, items\n\n\ndef format_document_number', '    from .customer_text import sanitize_snapshot\n    return sanitize_snapshot(document, items)\n\n\ndef format_document_number')
change(p,'    data = offer_defaults(M)\n    data.update(values or {})', '    from .customer_text import sanitize_snapshot\n    values, items = sanitize_snapshot(values, items)\n    data = offer_defaults(M)\n    data.update(values or {})')
change(p,'    return dict(row), [dict(item) for item in items]', '    from .customer_text import sanitize_snapshot\n    return sanitize_snapshot(dict(row), [dict(item) for item in items])')
p=src/'v750_context_filters_offer_format.py'
change(p,'        return document, prepared\n\n    service.draft_from_supplier_offer', '        from price_lists_domain.issued_offers.customer_text import sanitize_snapshot\n        return sanitize_snapshot(document, prepared)\n\n    service.draft_from_supplier_offer')
change(p,'            ) + 2\n            try:\n                filter_frame.configure(height=height)', '            ) + 2\n            height = max(52, height)\n            try:\n                filter_frame.pack_propagate(False)\n                filter_frame.grid_propagate(False)\n                filter_frame.configure(height=height)')
change(p,'            def sync(*_args: Any) -> None:\n                if (', '            def sync(*_args: Any) -> None:\n                nonlocal height\n                if (')
change(p,'                try:\n                    visible = displayed_columns(tree)', '''                try:
                    measured = max([52] + [int(widget.winfo_reqheight()) + 2
                        for _column, widget in cells if _widget_exists(widget)])
                    if measured != height:
                        height = measured
                        filter_frame.configure(height=height)
                    visible = displayed_columns(tree)''')
change(p,'            schedule_filter_sync(tree)\n        except Exception:\n            pass\n\n    M.attach_filter_bar', '''            schedule_filter_sync(tree)
            # Let fonts, DatePicker and combo children finish requesting space.
            for delay in (60, 180):
                tree.after(delay, lambda current=tree: schedule_filter_sync(current))
        except Exception:
            pass

    M.attach_filter_bar''')
p=offer/'corporate_renderer.py'
change(p,'        self.M, self.document, self.items = M, dict(document), [dict(i) for i in items]', '        from .customer_text import sanitize_snapshot\n        self.M = M\n        self.document, self.items = sanitize_snapshot(document, items)')
p=offer/'template_layout.py'
change(p,'    "title": "CENOVÁ NABÍDKA", "show_images": True,', '''    "title": "CENOVÁ NABÍDKA", "show_images": True,
    "number_in_header": True, "edit_opening_hours": False,
    "opening_hours": "Po – Čt: 7:30 – 15:30\\nPá: 8:30 – 15:00",''')
change(p,'    for key in ("title", "contacts_text", "closing_note", "signature_path"):', '    for key in ("title", "contacts_text", "closing_note", "signature_path", "opening_hours"):')
change(p,'    if not result["title"]', '''    if len(result["opening_hours"].splitlines()) > 4 or len(result["opening_hours"]) > 160:
        raise ValueError("Otevírací doba: nejvýše 4 řádky a 160 znaků.")
    if not result["title"]''')
change(p,'                "closing_columns", "show_group_subtotals", "zebra_rows"):', '                "closing_columns", "show_group_subtotals", "zebra_rows",\n                "number_in_header", "edit_opening_hours"):')
text=p.read_text(encoding='utf-8');text += '''\n\ndef is_original_asset(value, key):
    """Only overlay known TURTO art, never an unrelated user's graphic."""
    import hashlib
    if value == key:
        return True
    try:
        original = Path(asset_path(key)).read_bytes()
        return hashlib.sha256(Path(asset_path(value)).read_bytes()).digest() == hashlib.sha256(original).digest()
    except (OSError, TypeError):
        return False
''';p.write_text(text,encoding='utf-8')
p=offer/'template_settings.py'
change(p,'("columns","Sloupce"),("blocks","Dolní bloky")):', '("columns","Sloupce"),("blocks","Dolní bloky"),("branding","Záhlaví a zápatí")):')
change(p,'        preview=M.ttk.Frame(outer);preview.grid', '''        tab=self.tabs["branding"]
        check(tab,0,"Číslo nabídky do horního pruhu TURTO","number_in_header")
        check(tab,1,"Nahradit původní otevírací dobu vlastním textem","edit_opening_hours")
        M.ttk.Label(tab,text="Otevírací doba (max. 4 řádky)").grid(row=2,column=0,columnspan=3,sticky="w",pady=(12,4))
        text=M.tk.Text(tab,height=5,width=32,font=("Calibri",10),wrap="word",undo=True)
        text.grid(row=3,column=0,columnspan=3,sticky="ew")
        self.texts["opening_hours"]=text
        text.bind("<<Modified>>",self.text_changed)
        M.ttk.Label(tab,text="Zaškrtněte nahrazení a zadejte dny a časy. Prázdný text otevírací dobu skryje. Logo a ostatní grafika se nemění. Úprava platí pro původní grafiku TURTO a její přesné kopie; u vlastní jiné grafiky se nic nepřekrývá.",wraplength=320).grid(row=4,column=0,columnspan=3,sticky="w",pady=12)
        preview=M.ttk.Frame(outer);preview.grid''')
change(p,'for key in ("type","columns","blocks"):self.notebook.tab', 'for key in ("type","columns","blocks","branding"):self.notebook.tab')
p=offer/'professional_workflow.py'
change(p,'        if self.status == "current":\n            return f"Aktuální PDF', '        if self.status == "unsafe":\n            return "Starší PDF obsahuje interní cenu – vytvořte nový výstup"\n        if self.status == "current":\n            return f"Aktuální PDF')
change(p,'    payload = {field: _canonical(template.get(field)) for field in fields}', '    payload = {field: _canonical(template.get(field)) for field in fields}\n    payload["customer_output_policy"] = "7.9.2"')
change(p,'    if path is None or not path.is_file():\n        status = "missing"', '''    from price_lists_domain.issued_offers.customer_text import has_private_text
    if path is None or not path.is_file():
        status = "missing"
    elif has_private_text(snapshot, snapshot.get("items") or []):
        status = "unsafe"''')
change(p,'    locked = bool(document.get("locked"))\n    if (', '''    locked = bool(document.get("locked"))
    if locked and state.status == "unsafe":
        raise ValueError("Archivované PDF obsahuje interní zdrojovou cenu. Vytvořte kopii nabídky a vydejte nové PDF; původní archiv se nepřepisuje.")
    if (''')
change(p,'## Logo zůstává originální\n', '''## Záhlaví, číslo nabídky a otevírací doba

V Šablonách PDF otevřete vlastní kopii šablony a záložku Záhlaví a zápatí. Volba Číslo nabídky do horního pruhu vloží číslo vedle původního nápisu CENOVÁ NABÍDKA a vynechá jeho duplicitu v těle. Datum zůstává. U jiné vlastní grafiky se číslo bezpečně zobrazí v těle stránky.

Zaškrtněte Nahradit původní otevírací dobu vlastním textem. Zadejte nejvýše 4 řádky dnů a časů; prázdný text dobu skryje. Vypnutím volby obnovíte původní podobu. Uložte vlastní kopii šablony a zvolte ji v nabídce. Změna platí pro nově vytvořené PDF, nikoli starší archiv.

## Ochrana interních cen

Označené zdrojové a nákupní ceny se z popisu při převzetí, načtení a výstupu oddělují do interní poznámky. Technické rozměry ani nákupní hodnoty pro výpočet marže se nemění. Již vytvořená PDF se sama neopraví: u konceptu vytvořte nový výstup; u uzamčené nabídky použijte kopii. Starší PDF se zjištěnou interní cenou nelze znovu použít pro odeslání.

## Logo zůstává originální
''')
p=offer/'corporate_renderer.py'
change(p,'    def new_page(self, table=False):', '''    def artwork_rect(self, value, rect):
        # insert_image(keep_proportion=True) centers inside this rectangle.
        with fitz.open(template_layout.asset_path(value)) as art:
            source = art[0].rect
        factor = min(rect.width/source.width, rect.height/source.height)
        w, h = source.width*factor, source.height*factor
        return fitz.Rect(rect.x0+(rect.width-w)/2, rect.y0+(rect.height-h)/2,
                         rect.x0+(rect.width+w)/2, rect.y0+(rect.height+h)/2)

    def header_number(self, rect):
        value = str(self.document.get("document_number") or "KONCEPT")
        r = self.artwork_rect(self.template["header_path"], rect)
        # Free right-hand portion of the original red stripe, away from logo/title.
        box = fitz.Rect(r.x0+r.width*.282, r.y0+r.height*.505,
                        r.x0+r.width*.483, r.y0+r.height*.85)
        size = min(11.0, box.height/(self.fonts[1].ascender-self.fonts[1].descender))
        while self.fonts[1].text_length(value, fontsize=size)>box.width and size>5:
            size -= .25
        if self.fonts[1].text_length(value, fontsize=size)>box.width:
            raise ValueError("Číslo je příliš dlouhé pro horní pruh. Vypněte číslo v záhlaví v nastavení šablony.")
        self.text(box.x0,box.y0,value,True,size,(1,1,1),"right",box.width)
        # Make the caption embedded in the original bitmap searchable without
        # drawing a second title or changing the corporate artwork.
        self.page.insert_text((r.x0+r.width*.10, box.y0+size), "CENOVÁ NABÍDKA",
                              fontname="TRBold", fontsize=8, render_mode=3)

    def footer_hours(self, rect):
        r = self.artwork_rect(self.template["footer_path"], rect)
        # Only the warehouse hours to the right of the original red separator.
        box = fitz.Rect(r.x0+r.width*.647,r.y0+r.height*.345,
                        r.x1,r.y0+r.height*.965)
        self.page.draw_rect(box,color=None,fill=(1,1,1))
        hours = self.style["opening_hours"]
        if not hours:
            return
        lines = ["Prodejní sklad"] + hours.splitlines()
        size = min(7.0, box.height/(len(lines)*1.22))
        width = box.width-5
        while max(self.fonts[0].text_length(s,fontsize=size) for s in lines)>width and size>4.5:
            size -= .25
        if size<4.5:
            raise ValueError("Otevírací doba je příliš dlouhá pro zápatí; zkraťte text nebo zvětšete zápatí.")
        for i,line in enumerate(lines):
            self.text(box.x0+3,box.y0+i*size*1.22,line,size=size)

    def new_page(self, table=False):''')
change(p,'                self.asset(t.get("header_path"), fitz.Rect(self.left,8,self.right,8+t["header_height_mm"]*MM))', '''                rect = fitz.Rect(self.left,8,self.right,8+t["header_height_mm"]*MM)
                self.asset(t.get("header_path"), rect)
                if self.number_in_header:
                    self.header_number(rect)''')
change(p,'                self.asset(t.get("footer_path"), fitz.Rect(self.left,HEIGHT-12-t["footer_height_mm"]*MM,self.right,HEIGHT-12))', '''                rect = fitz.Rect(self.left,HEIGHT-12-t["footer_height_mm"]*MM,self.right,HEIGHT-12)
                self.asset(t.get("footer_path"), rect)
                if self.style["edit_opening_hours"] and template_layout.is_original_asset(t.get("footer_path"), "builtin:turto-offer-footer"):
                    self.footer_hours(rect)''')
change(p,'        self.size = self.style["font_size"]', '''        self.number_in_header = bool(self.style["number_in_header"] and self.template["header_height_mm"]
            and template_layout.is_original_asset(self.template.get("header_path"), "builtin:turto-offer-header"))
        self.size = self.style["font_size"]''')
change(p,'            self.text(self.left,self.y,self.document.get("document_number",""),True,size=8,color=self.navy)', '''            if not self.number_in_header or not t.get("header_every_page",True):
                self.text(self.left,self.y,self.document.get("document_number",""),True,size=8,color=self.navy)''')
start='        title=self.wrap(self.style["title"],self.width*.6,True,17)'
end='        self.line(self.y,color=self.navy)'
text=p.read_text(encoding='utf-8');a=text.index(start);b=text.index(end,a);old=text[a:b]
new='''        if self.number_in_header:
            self.text(self.right-170,self.y,"Datum: "+str(self.M.fmt_date(self.document.get("issue_date"))),size=8.5,align="right",width=170)
            self.y += 20
        else:
'''+''.join('    '+line+'\n' for line in old.rstrip('\n').split('\n'))
text=text[:a]+new+text[b:];p.write_text(text,encoding='utf-8')
print('Source edits applied')
