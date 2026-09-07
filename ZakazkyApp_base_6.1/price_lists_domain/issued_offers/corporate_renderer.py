"""Measured A4 corporate quotation. One layout pass owns PDF and click regions.

No logo drawing, no customer price calculations, no mutable global service hooks.
"""
from __future__ import annotations
import os
import tempfile
from pathlib import Path
from typing import Any
import fitz
from . import service, template_layout, font_support, offer_images

MM = 72 / 25.4
WIDTH, HEIGHT = 595.276, 841.890


def _color(hex_value):
    return tuple(int(hex_value[i:i+2], 16) / 255 for i in (1, 3, 5))


def _money(value, currency):
    label = "Kč" if currency == "CZK" else currency
    return f"{service.number(value):,.2f}".replace(",", " ").replace(".", ",") + " " + label


def _qty(value):
    return f"{service.number(value):,.3f}".replace(",", " ").replace(".", ",").rstrip("0").rstrip(",")


class Layout:
    def __init__(self, M, document, items, template):
        from .customer_text import sanitize_snapshot
        self.M = M
        self.document, self.items = sanitize_snapshot(document, items)
        self.style = template_layout.normalize(template.get("layout_json"))
        self.template = template_layout.validate_geometry(template, self.style)
        self.left = self.template["margin_left_mm"] * MM
        self.right = WIDTH - self.template["margin_right_mm"] * MM
        self.width = self.right - self.left
        self.top = 8 + (self.template["header_height_mm"] + self.template["body_top_gap_mm"]) * MM
        self.bottom = HEIGHT - 12 - (self.template["footer_height_mm"] + self.template["body_bottom_gap_mm"]) * MM
        self.number_in_header = bool(self.style["number_in_header"] and self.template["header_height_mm"]
            and template_layout.is_original_asset(self.template.get("header_path"), "builtin:turto-offer-header"))
        self.size = self.style["font_size"]
        self.pad = self.style["row_padding_mm"] * MM
        self.ink = (0.08, 0.10, 0.12)
        self.muted = (0.34, 0.38, 0.40)
        self.rule = (0.81, 0.84, 0.86)
        self.navy = _color(self.style["primary_color"])
        self.red = _color(self.style["section_color"])
        self.grey = _color(self.style["subsection_color"])
        self.columns = template_layout.columns_for(self.style, self.width)
        x = self.left
        for c in self.columns:
            c["x0"], c["x1"] = x, x + c["width_pt"]
            x = c["x1"]
        regular, bold = font_support._font_files()
        self.font_files = (regular, bold)
        self.fonts = [fitz.Font(fontfile=str(p)) if p else fitz.Font("hebo" if n else "helv") for n, p in enumerate((regular, bold))]
        self.leading = max(f.ascender - f.descender for f in self.fonts) * self.size * 1.04
        self.pdf = fitz.open()
        self.page = None
        self.y = self.top
        self.regions = []
        self.image_cache = {}
        self.currency = str(document.get("currency") or "CZK")
        self.header_lines = [self.wrap(c["label"], c["width_pt"]-8, True, self.size-.5) for c in self.columns]
        self.header_height = max(len(lines) for lines in self.header_lines) * self.leading + 8
        if self.header_height > min(130, (self.bottom-self.top)/3):
            self.pdf.close()
            raise ValueError("Záhlaví tabulky je příliš vysoké. Zkraťte popisky nebo rozšiřte sloupce.")

    def wrap(self, text, width, bold=False, size=None):
        size = size or self.size
        font = self.fonts[int(bool(bold))]
        result = []
        for paragraph in str(text or "").replace("\r", "").split("\n"):
            line = ""
            for word in paragraph.split():
                test = (line + " " + word).strip()
                if font.text_length(test, fontsize=size) <= width:
                    line = test
                    continue
                if line:
                    result.append(line)
                    line = ""
                # Split an overlong code/URL, never silently truncate it.
                while word and font.text_length(word, fontsize=size) > width:
                    length = 1
                    while length < len(word) and font.text_length(word[:length+1], fontsize=size) <= width:
                        length += 1
                    result.append(word[:length])
                    word = word[length:]
                line = word
            result.append(line)
        return result or [""]

    def text(self, x, y, value, bold=False, size=None, color=None, align="left", width=None):
        size = size or self.size
        font = self.fonts[int(bool(bold))]
        value = str(value or "")
        if width is not None:
            measured = font.text_length(value, fontsize=size)
            if align == "right":
                x += width - measured
            elif align == "center":
                x += (width - measured) / 2
        self.page.insert_text((x, y + font.ascender * size), value,
            fontsize=size, fontname="TRBold" if bold else "TRRegular", color=color or self.ink)

    def lines(self, x, y, lines, bold=False, size=None, color=None, align="left", width=None):
        for index, value in enumerate(lines):
            self.text(x, y + index*self.leading, value, bold, size, color, align, width)

    def line(self, y, left=None, right=None, color=None):
        self.page.draw_line((self.left if left is None else left, y),
            (self.right if right is None else right, y), color=color or self.rule, width=.5)

    def asset(self, value, rect):
        if not value:
            return
        path = Path(template_layout.asset_path(value))
        if not path.is_file():
            raise ValueError(f"Chybí grafika šablony: {path.name}. Opravte cestu v Šablonách PDF.")
        if path.suffix.lower() == ".pdf":
            with fitz.open(path) as source:
                if not source.page_count:
                    raise ValueError("Grafika šablony obsahuje prázdné PDF.")
                self.page.show_pdf_page(rect, source, 0, keep_proportion=True)
        else:
            self.page.insert_image(rect, stream=path.read_bytes(), keep_proportion=True)

    def artwork_rect(self, value, rect):
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

    def new_page(self, table=False):
        self.page = self.pdf.new_page(width=WIDTH, height=HEIGHT)
        for n, (name, p) in enumerate(zip(("TRRegular", "TRBold"), self.font_files)):
            if p:
                self.page.insert_font(fontname=name, fontfile=str(p))
            else:
                self.page.insert_font(fontname=name, fontbuffer=self.fonts[n].buffer)
        first = self.pdf.page_count == 1
        t = self.template
        if first or t.get("header_every_page", True):
            if t["header_height_mm"]:
                rect = fitz.Rect(self.left,8,self.right,8+t["header_height_mm"]*MM)
                self.asset(t.get("header_path"), rect)
                if self.number_in_header:
                    self.header_number(rect)
        if first or t.get("footer_every_page", True):
            if t["footer_height_mm"]:
                rect = fitz.Rect(self.left,HEIGHT-12-t["footer_height_mm"]*MM,self.right,HEIGHT-12)
                self.asset(t.get("footer_path"), rect)
                if self.style["edit_opening_hours"] and template_layout.is_original_asset(t.get("footer_path"), "builtin:turto-offer-footer"):
                    self.footer_hours(rect)
        self.y = self.top
        if not first:
            if not self.number_in_header or not t.get("header_every_page",True):
                self.text(self.left,self.y,self.document.get("document_number",""),True,size=8,color=self.navy)
            self.text(self.right-180,self.y,"Pokračování cenové nabídky",size=8,color=self.muted,align="right",width=180)
            self.y += self.leading + 7
        if table:
            self.table_header()

    def ensure(self, height, table=False):
        if self.page is None or self.y+height > self.bottom:
            self.new_page(table)

    def table_header(self):
        y=self.y
        self.page.draw_rect(fitz.Rect(self.left,y,self.right,y+self.header_height),color=None,fill=self.navy)
        for c, lines in zip(self.columns,self.header_lines):
            alignment = "left" if c["key"] in {"name","code"} else "right" if c["key"] in {"unit_price","total","recommended"} else "center"
            self.lines(c["x0"]+4,y+4,lines,True,self.size-.5,(1,1,1),alignment,c["width_pt"]-8)
        self.y += self.header_height

    def intro(self):
        self.new_page()
        if self.number_in_header:
            self.text(self.right-170,self.y,"Datum: "+str(self.M.fmt_date(self.document.get("issue_date"))),size=8.5,align="right",width=170)
            self.y += 20
        else:
            title=self.wrap(self.style["title"],self.width*.6,True,17)
            # The normal title is a single line; long custom titles remain searchable.
            for i,line in enumerate(title):
                self.text(self.left,self.y+i*21,line,True,17,self.navy)
            self.text(self.right-170,self.y,self.document.get("document_number",""),True,10,align="right",width=170)
            self.text(self.right-170,self.y+16,"Datum: "+str(self.M.fmt_date(self.document.get("issue_date"))),size=8.5,align="right",width=170)
            self.y += max(36,21*len(title)+9)
        self.line(self.y,color=self.navy)
        self.y += 11
        w=(self.width-24)/2
        parties=[]
        for prefix,title in (("issuer","DODAVATEL"),("customer","ODBĚRATEL")):
            lines=[]
            d=self.document
            for value,bold in ((d.get(prefix+"_name_snapshot"),True),(d.get(prefix+"_address_snapshot"),False)):
                if value:
                    lines.extend((s,bold) for s in self.wrap(value,w,bold))
            ids="   ".join(label+str(d.get(prefix+key)) for label,key in (("IČ: ","_ico_snapshot"),("DIČ: ","_dic_snapshot")) if d.get(prefix+key))
            if ids: lines.extend((s,False) for s in self.wrap(ids,w))
            for key,label in (("contact","Obchodník: " if prefix=="issuer" else "Kontakt: "),("phone","Telefon: "),("email","E-mail: ")):
                value=d.get(prefix+"_"+key+"_snapshot")
                if value: lines.extend((s,False) for s in self.wrap(label+str(value),w))
            if prefix=="issuer" and d.get("issuer_bank_snapshot"):
                lines.extend((s,False) for s in self.wrap("Bankovní spojení: "+str(d["issuer_bank_snapshot"]),w))
            parties.append((title,lines))
        self.blocks(parties, gap=24)
        self.y += 8
        value=self.document.get("project_name") or self.document.get("action_name") or self.document.get("offer_subject") or ""
        self.band("Akce: "+str(value), self.grey, self.ink, False)
        subject=self.document.get("offer_subject") or ""
        if subject and subject != value:
            self.paragraph("Předmět: "+subject)
        if self.document.get("customer_reference"):
            self.paragraph("Reference: "+str(self.document["customer_reference"]))
        self.y += 10
        self.ensure(self.header_height+45)
        self.table_header()

    def band(self,text,fill,color,bold=True,table=False):
        lines=self.wrap(text,self.width-12,bold,self.size-.3)
        height=len(lines)*self.leading+7
        capacity=self.bottom-self.top-self.header_height-30
        self.ensure(min(height+30,capacity),table)
        while lines:
            count=max(0,int((self.bottom-self.y-7)/self.leading))
            if count<1:
                self.new_page(table);continue
            part,lines=lines[:count],lines[count:]
            height=len(part)*self.leading+7
            self.page.draw_rect(fitz.Rect(self.left,self.y,self.right,self.y+height),color=None,fill=fill)
            self.lines(self.left+6,self.y+3.5,part,bold,self.size-.3,color)
            self.y += height
            if lines:self.new_page(table)

    def paragraph(self,text,bold=False):
        lines=self.wrap(text,self.width,bold)
        for s in lines:
            self.ensure(self.leading+3)
            self.text(self.left,self.y,s,bold)
            self.y += self.leading
        self.y += 5

    def image(self,item):
        key=(item.get("image_file_snapshot"),item.get("image_asset_key_snapshot"),item.get("source_supplier_offer_item_id"),id(item.get("_image_bytes")))
        if key not in self.image_cache:
            self.image_cache[key] = offer_images.resolve(self.M,item)
        return self.image_cache[key]

    def row(self, raw, index, position, measure_only=False):
        item=service.normalize_item(raw)
        name=str(item.get("name") or item.get("internal_name_snapshot") or "")
        code=str(item.get("internal_code_snapshot") or item.get("product_code") or "")
        has_code=any(c["key"]=="code" for c in self.columns)
        if code and not item.get("supplier_presentation_snapshot") and not has_code and code not in name:
            name=code+" · "+name
        description=str(item.get("description") or "")
        if description==name: description=""
        if item.get("line_note"): description += ("\n" if description else "")+str(item["line_note"])
        values={"position":str(position),"quantity":_qty(item.get("quantity")),"code":code,
            "unit":str(item.get("unit") or ""),"unit_price":_money(item.get("unit_price"),self.currency),
            "total":_money(item.get("total_price"),self.currency),
            "recommended":_money(item.get("recommended_unit_price"),self.currency) if item.get("show_recommended_price",1) else "",
            "discount":_qty(item.get("discount_pct"))+" %"}
        cells=[]
        blob=self.image(item) if self.style["show_images"] and any(c["key"]=="image" for c in self.columns) else None
        for c in self.columns:
            key=c["key"]
            if key=="name":
                lines=[(s,True) for s in self.wrap(name,c["width_pt"]-10,True)]
                if description: lines += [(s,False) for s in self.wrap(description,c["width_pt"]-10)]
            elif key=="image": lines=[]
            else: lines=[(s,key=="total") for s in self.wrap(values.get(key,""),c["width_pt"]-8,key=="total")]
            cells.append((c,lines))
        count=max(len(lines) for c,lines in cells)
        image_height=self.style["image_height_mm"]*MM if blob else 0
        height=max(count*self.leading,image_height)+2*self.pad
        if measure_only:return height
        max_row=self.bottom-self.top-self.header_height-30
        if height <= max_row: self.ensure(height,True)
        offset=0
        while offset < count:
            available=self.bottom-self.y-2*self.pad
            chunk=max(0,int(available/self.leading))
            if chunk < 1 or (offset==0 and blob and available < image_height):
                self.new_page(True);continue
            take=min(count-offset,chunk)
            part_height=max(take*self.leading,image_height if offset==0 else 0)+2*self.pad
            y=self.y
            if self.style["zebra_rows"] and position%2==0:
                self.page.draw_rect(fitz.Rect(self.left,y,self.right,y+part_height),color=None,fill=(.98,.985,.988))
            for c,lines in cells:
                key=c["key"]
                if key=="image" and blob and offset==0:
                    rect=fitz.Rect(c["x0"]+4,y+self.pad,c["x1"]-4,y+part_height-self.pad)
                    self.page.insert_image(rect,stream=blob,keep_proportion=True)
                selected=lines[offset:offset+take]
                align="left" if key in {"name","code"} else "right" if key in {"unit_price","total","recommended"} else "center"
                top=y+self.pad
                if offset==0 and len(lines)<take: top += max(0,(part_height-2*self.pad-len(lines)*self.leading)/2)
                for n,(s,bold) in enumerate(selected):
                    self.text(c["x0"]+4,top+n*self.leading,s,bold,align=align,width=c["width_pt"]-8)
            self.line(y+part_height)
            self.regions.append(dict(page=self.pdf.page_count-1,index=index,x0=self.left,y0=y,x1=self.right,y1=y+part_height))
            self.y += part_height
            offset += take
            if offset<count: self.new_page(True)

    def blocks(self,blocks,gap=16):
        """Flow closing columns together, keeping short contact blocks on one page."""
        if not blocks: return
        width=(self.width-gap*(len(blocks)-1))/len(blocks)
        wrapped=[]
        for title,rows in blocks:
            lines=[]
            for text,bold in rows:
                lines.extend((s,bold) for s in self.wrap(text,width,bold))
            wrapped.append((self.wrap(title,width,True,self.size-.2),lines))
        heading_height=max(len(title) for title,_ in wrapped)*self.leading+16
        count=max(len(lines) for _,lines in wrapped)
        offset=0
        self.ensure(min(count*self.leading+heading_height,self.bottom-self.top-25))
        while offset < max(1,count):
            available=int((self.bottom-self.y-heading_height)/self.leading)
            if available<1: self.new_page();continue
            take=min(max(1,count)-offset,available)
            y=self.y
            for n,(title,lines) in enumerate(wrapped):
                x=self.left+n*(width+gap)
                self.lines(x,y,title,True,self.size-.2,self.navy)
                self.line(y+heading_height-13,x,x+width)
                for i,(text,bold) in enumerate(lines[offset:offset+take]):
                    self.text(x,y+heading_height-6+i*self.leading,text,bold)
            self.y += heading_height+take*self.leading
            offset += take
            if offset<count: self.new_page()

    def body(self):
        grouper=getattr(self.M,"group_issued_offer_items",None) or getattr(service,"group_offer_items",None)
        tokens=grouper(self.items) if callable(grouper) else [{"kind":"item","index":i,"item":item} for i,item in enumerate(self.items)]
        position=0; last_category=None; group_total=0; in_group=False
        def subtotal():
            if in_group and self.style["show_group_subtotals"]:
                self.ensure(self.leading+12,True)
                self.text(self.left,self.y+4,"Mezisoučet oddílu bez DPH",size=self.size-.5,color=self.muted)
                self.text(self.right-140,self.y+4,_money(group_total,self.currency),True,align="right",width=140)
                self.y += self.leading+12
        tokens=list(tokens)
        def next_row_height(at):
            if at+1<len(tokens) and tokens[at+1]["kind"]=="item":
                nxt=tokens[at+1]
                if nxt["item"].get("row_type","product")=="product":
                    return self.row(nxt["item"],int(nxt.get("index",0)),position+1,measure_only=True)
            return 35
        for at,token in enumerate(tokens):
            if token["kind"]=="group":
                subtotal(); group_total=0; in_group=True
                category=str(token.get("category") or "")
                subgroup=str(token.get("subgroup") or "")
                # At least a header plus the first product row must fit together.
                headings=[t for t in (category if category!=last_category and category!="Nezařazeno" else "",subgroup if subgroup!="Bez podskupiny" else "") if t]
                h=sum(len(self.wrap(t,self.width-12,True,self.size-.3))*self.leading+7 for t in headings)
                self.ensure(min(h+next_row_height(at),self.bottom-self.top-self.header_height-30),True)
                if category and category != last_category and category != "Nezařazeno":
                    self.band(category,self.red,(1,1,1),True,True)
                if subgroup and subgroup != "Bez podskupiny":
                    self.band(subgroup,self.grey,self.navy,True,True)
                last_category=category
                continue
            item=dict(token["item"]);index=int(token.get("index",0))
            typ=item.get("row_type","product")
            if typ=="heading":
                subtotal();group_total=0;in_group=False
                heading=item.get("name") or item.get("description") or ""
                h=len(self.wrap(heading,self.width-12,True,self.size-.3))*self.leading+7
                self.ensure(min(h+next_row_height(at),self.bottom-self.top-self.header_height-30),True)
                self.band(heading,self.red,(1,1,1),True,True)
                last_category=None
            elif typ=="text":
                self.paragraph(item.get("description") or item.get("name") or "")
            else:
                position += 1
                self.row(item,index,position)
                group_total += service.normalize_item(item)["total_price"]
        subtotal()

    def closing(self):
        totals=service.calculate_totals(self.items,self.document.get("global_discount_pct"))
        self.ensure(110)
        self.y += 9
        self.line(self.y,color=self.navy)
        self.y += 8
        def amount(label,value,big=False):
            value_width=min(155,self.width*.32)
            label_x=self.left+self.width*.25
            label_width=self.right-value_width-12-label_x
            labels=self.wrap(label,label_width,big,self.size-.3)
            height=max(25,len(labels)*self.leading+8)
            self.ensure(height)
            self.lines(label_x,self.y+3,labels,big,self.size-.3)
            x=self.right-value_width
            if big:
                self.page.draw_rect(fitz.Rect(x,self.y,self.right,self.y+height-2),color=None,fill=self.grey)
            value_text=_money(value,self.currency)
            size=12 if big else self.size
            while size>7.5 and self.fonts[1].text_length(value_text,fontsize=size)>value_width-10:
                size-=.25
            if self.fonts[1].text_length(value_text,fontsize=size)>value_width-10:
                raise ValueError("Částka je příliš dlouhá pro souhrn ceny.")
            self.text(x+5,self.y+3,value_text,True,size,align="right",width=value_width-10)
            self.y += height

        if totals.global_discount:
            amount("Cena položek bez DPH",totals.items_subtotal)
            amount("Celková sleva "+_qty(self.document.get("global_discount_pct"))+" %",-totals.global_discount)
        amount("Vaše cena celkem bez DPH:",totals.subtotal_net,True)
        if self.style["show_vat_summary"]:
            amount("DPH",totals.vat_total)
            amount("Cena včetně DPH",totals.total_gross)
        else:
            rates=sorted({service.number(i.get("vat_rate"),21) for i in self.items if i.get("row_type") not in {"heading","text"}})
            note="Ceny jsou uvedeny bez DPH"+(" "+_qty(rates[0])+" %." if len(rates)==1 else ".")
            self.text(self.right-280,self.y,note,size=7.5,color=self.muted,align="right",width=280)
            self.y += self.leading
        self.y += 15
        d=self.document
        terms=[]
        for label,value in (("Platnost nabídky",self.M.fmt_date(d.get("valid_to"))),
            ("Termín dodání",d.get("delivery_time")),("Místo dodání",d.get("delivery_address")),
            ("Splatnost",d.get("payment_terms")),("Dodací podmínky",d.get("delivery_terms"))):
            if value: terms.append((label+": "+str(value),False))
        blocks=[("OBCHODNÍ PODMÍNKY",terms)]
        if self.style["show_contacts"] and self.style["contacts_text"]:
            blocks.append(("DŮLEŽITÉ KONTAKTY",[(s,False) for s in self.style["contacts_text"].splitlines()]))
        if self.style["show_salesperson"]:
            salesperson=[(d.get("salesperson_snapshot") or d.get("issuer_contact_snapshot") or "",True)]
            salesperson += [(str(d.get(k) or ""),False) for k in ("issuer_phone_snapshot","issuer_email_snapshot") if d.get(k)]
            blocks.append(("Za TURTO s.r.o.",salesperson))
        if self.style["closing_columns"]: self.blocks(blocks)
        else:
            for b in blocks: self.blocks([b]);self.y+=9
        for text in (d.get("customer_note"),self.style["closing_note"]):
            if text:
                self.y+=7;self.paragraph(text)
        if self.style["signature_path"]:
            self.ensure(85)
            self.asset(self.style["signature_path"],fitz.Rect(self.right-140,self.y,self.right,self.y+80));self.y+=85
        return totals

    def save(self,target):
        target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
        try:
            self.intro();self.body();totals=self.closing()
            for i in range(self.pdf.page_count):
                self.page=self.pdf[i]
                self.text(self.right-120,HEIGHT-10,f"Strana {i+1}/{self.pdf.page_count}",size=6.5,color=self.muted,align="right",width=120)
            self.pdf.set_metadata({"title":self.document.get("document_number") or self.style["title"],"author":"TURTO s.r.o.","creator":"TURTO CRM · firemní šablona"})
            self.pdf.subset_fonts()
            fd,temp=tempfile.mkstemp(prefix=".turto_pdf_",suffix=".pdf",dir=str(target.parent));os.close(fd)
            try:
                self.pdf.save(temp,garbage=3,deflate=True)
                os.replace(temp,target)
            finally:
                if os.path.exists(temp): os.unlink(temp)
            return dict(path=target,regions=self.regions,pages=self.pdf.page_count,totals=totals)
        finally:
            self.pdf.close()


def render(M,document,items,template,target):
    return Layout(M,document,items,template).save(target)
