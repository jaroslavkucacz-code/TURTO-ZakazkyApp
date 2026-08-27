import math
import hashlib
import io
import os
import re
from pathlib import Path

import fitz
import xlsxwriter

CODE_RE = re.compile(r'^\d{3}-\d{3}-\d{3}$')
QTY_RE = re.compile(r'^(\d+(?:[.,]\d+)?)\s*ks$', re.I)
MONEY_LINE_RE = re.compile(r'^-?\d[\d ]*(?:,\d{2})?$')
PCT_RE = re.compile(r'^\d+(?:,\d+)?\s*%$')


def cz_num(text):
    return float(str(text).strip().replace(' ', '').replace('.', '').replace(',', '.'))


def _explicit_discount_for_row(page, code):
    """
    Read the percentage printed in the same visual row as the product code.
    This is the authoritative GEROtop discount. Shape/order of price columns
    does not matter.
    """
    code_y=None
    try:
        for b in page.get_text('blocks'):
            if clean_text(b[4]) == code:
                code_y=(b[1]+b[3])/2
                break
        if code_y is None:
            return None

        candidates=[]
        for b in page.get_text('blocks'):
            cy=(b[1]+b[3])/2
            if abs(cy-code_y) > 8:
                continue
            txt=clean_text(b[4])
            for m in re.finditer(r'(\d+(?:[,.]\d+)?)\s*%',txt):
                try:
                    candidates.append(float(m.group(1).replace(',','.')))
                except Exception:
                    pass

        if candidates:
            return candidates[0]
    except Exception:
        pass
    return None


def clean_text(text):
    return ' '.join(str(text).replace('\ufb01','fi').replace('\ufb02','fl').split())


def strip_brand(text):
    text = re.sub(r'^\s*GEROtop\s*[®]?\s*', '', text, flags=re.I)
    return text.strip()


def detect_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        txt = "\n".join(page.get_text("text") for page in doc[:2]).upper()
        return (
            "GEROTOP" in txt
            and "NABÍDK" in txt
            and ("PROSTUP" in txt or "ČÍSLO NÁVRHU" in txt or "NABÍDKA ČÍSLO" in txt)
        )
    except Exception:
        return False

def _product_images(doc, page_no):
    page = doc[page_no]
    found = []
    seen = set()
    for img in page.get_images(full=True):
        xref = img[0]
        for rect in page.get_image_rects(xref):
            # Product pictures are in the left image column.
            if rect.x0 > 110 or rect.y0 < 90:
                continue
            key = (round(rect.x0,1), round(rect.y0,1), round(rect.x1,1), round(rect.y1,1))
            if key in seen:
                continue
            seen.add(key)
            try:
                data = doc.extract_image(xref)
                found.append({
                    'rect': rect,
                    'bytes': data['image'],
                    'ext': data.get('ext','png'),
                })
            except Exception:
                pass
    return found


def _code_y(page, code):
    for b in page.get_text('blocks'):
        if clean_text(b[4]) == code:
            return (b[1] + b[3]) / 2
    return None


def _all_code_centers(page):
    result=[]
    for b in page.get_text('blocks'):
        txt=clean_text(b[4])
        if CODE_RE.fullmatch(txt):
            result.append((txt,(b[1]+b[3])/2))
    return result

def _extract_pdf_image_object(doc,img_tuple):
    """
    Extract original PDF image and correctly apply its SMask/alpha mask.
    The mask is decoded separately and attached as alpha before any white
    background compositing. This avoids false black rectangles.
    """
    from PIL import Image
    try:
        xref=int(img_tuple[0])
        smask=int(img_tuple[1] or 0) if len(img_tuple)>1 else 0

        base_data=doc.extract_image(xref)
        base_raw=base_data['image']
        base=Image.open(io.BytesIO(base_raw))
        base.load()

        # Normalize base without destroying colour information.
        if base.mode not in ('RGB','RGBA'):
            base=base.convert('RGBA' if 'A' in base.mode else 'RGB')

        if smask:
            try:
                mask_data=doc.extract_image(smask)
                mask=Image.open(io.BytesIO(mask_data['image']))
                mask.load()

                # SMask is grayscale alpha. Convert explicitly and match dimensions.
                if mask.mode!='L':
                    if 'A' in mask.mode:
                        mask=mask.getchannel('A')
                    else:
                        mask=mask.convert('L')
                if mask.size!=base.size:
                    mask=mask.resize(base.size)

                rgba=base.convert('RGBA')
                rgba.putalpha(mask)
                out=io.BytesIO()
                rgba.save(out,format='PNG')
                return out.getvalue(),'png'
            except Exception:
                # Try PyMuPDF pixmap mask composition as fallback.
                try:
                    base_pix=fitz.Pixmap(doc,xref)
                    mask_pix=fitz.Pixmap(doc,smask)
                    pix=fitz.Pixmap(base_pix,mask_pix)
                    return pix.tobytes('png'),'png'
                except Exception:
                    pass

        # No mask: return original bytes when possible.
        return base_raw,base_data.get('ext','png')
    except Exception:
        return None,None



def _white_image(raw):
    """Keep the product exactly as extracted, but place PDF alpha on plain white."""
    from PIL import Image
    try:
        im=Image.open(io.BytesIO(raw)).convert('RGBA')
        bg=Image.new('RGB',im.size,'white')
        bg.paste(im,mask=im.getchannel('A'))
        return bg
    except Exception:
        return Image.open(io.BytesIO(raw)).convert('RGB')


def _visual_hash(raw):
    from PIL import Image
    try:
        im=_white_image(raw)
        im.thumbnail((96,96))
        c=Image.new('RGB',(96,96),'white')
        c.paste(im,((96-im.width)//2,(96-im.height)//2))
        sm=c.resize((24,24))
        return hashlib.sha1(bytes((v//16)*16 for p in sm.getdata() for v in p)).hexdigest()
    except Exception:
        return hashlib.sha1(raw).hexdigest()


def _fit(im,max_w,max_h):
    if not im.width or not im.height:return im
    sc=min(max_w/im.width,max_h/im.height,1.0)
    if sc<1:
        im=im.resize((max(1,round(im.width*sc)),max(1,round(im.height*sc))))
    return im


def _compose_clean_images(entries):
    """
    V4.7.23: exactly one image per product.
    Choose the image with the largest displayed area in the PDF and ignore all
    supporting/alternative images. No collage composition.
    """
    if not entries:
        return None,None

    # Largest displayed rectangle = dominant image for the product row.
    area,raw=max(entries,key=lambda x:x[0])
    try:
        im=_white_image(raw)
        out=io.BytesIO()
        im.save(out,format='PNG',optimize=True)
        return out.getvalue(),'png'
    except Exception:
        return raw,'png'


def _trim_empty_outer_border(raw):
    # V4.7.20: no background removal / transparency conversion.
    im=_white_image(raw)
    out=io.BytesIO();im.save(out,format='PNG',optimize=True)
    return out.getvalue(),'png'


def _optimize_product_image(raw,max_px=300,quality=85):
    from PIL import Image
    try:
        im=_white_image(raw)
        im.thumbnail((max_px,max_px))
        out=io.BytesIO()
        im.save(out,format='JPEG',quality=quality,optimize=True,progressive=True)
        return out.getvalue(),'jpg'
    except Exception:
        return raw,'png'


def _center_for_excel_cell(raw,ext,target_ratio=1.0):
    return _optimize_product_image(raw,300,85)


def _render_row_product_images(doc,page_no,code,prev_code=None,next_code=None):
    page=doc[page_no]
    centers=_all_code_centers(page)
    current=[(c,y) for c,y in centers if c==code]
    if not current:
        return None,None
    current_y=current[0][1]
    entries=[]; seen=set()
    for img in page.get_images(full=True):
        xref=img[0]
        try:
            rects=page.get_image_rects(xref)
        except Exception:
            rects=[]
        for r in rects:
            if r.width<18 or r.height<18 or r.y0<65 or r.y1>page.rect.height-48:
                continue
            if r.width>page.rect.width*.70:
                continue
            cy=(r.y0+r.y1)/2
            nearest_code,nearest_y=min(centers,key=lambda p:abs(p[1]-cy))
            if nearest_code!=code or abs(nearest_y-current_y)>1:
                continue
            key=(xref,round(r.x0,1),round(r.y0,1),round(r.x1,1),round(r.y1,1))
            if key in seen:
                continue
            seen.add(key)
            try:
                raw,ext=_extract_pdf_image_object(doc,img)
                if raw:
                    entries.append((r.width*r.height,raw))
            except Exception:
                pass
    return _compose_clean_images(entries)

def _bold_terms_for_row(page, code):
    """Return bold text fragments belonging to the same product row as code."""
    centers=_all_code_centers(page)
    cur=[y for c,y in centers if c==code]
    if not cur:
        return []
    y=cur[0]
    ys=sorted(v for _,v in centers)
    prev=max([v for v in ys if v<y], default=y-120)
    nxt=min([v for v in ys if v>y], default=y+120)
    y0=(prev+y)/2
    y1=(y+nxt)/2

    terms=[]
    try:
        data=page.get_text("dict")
        for block in data.get("blocks",[]):
            for line in block.get("lines",[]):
                for span in line.get("spans",[]):
                    sy=(span["bbox"][1]+span["bbox"][3])/2
                    txt=clean_text(span.get("text","")).strip()
                    font=(span.get("font","") or "").lower()
                    flags=int(span.get("flags",0) or 0)
                    is_bold=("bold" in font) or bool(flags & 16)
                    if y0<=sy<y1 and is_bold and txt and txt!=code:
                        # prices/quantities are irrelevant to rich product description
                        if not re.fullmatch(r"[\d\s.,%€Kč-]+",txt):
                            terms.append(txt)
    except Exception:
        return []
    # longest first, unique, so phrases win over contained words
    out=[]
    for t in sorted(set(terms),key=len,reverse=True):
        if t not in out:
            out.append(t)
    return out


def _rich_parts(text, bold_terms, bold_fmt, normal_fmt):
    """Build XlsxWriter rich-string fragments while preserving original text."""
    if not text:
        return []
    terms=[t for t in (bold_terms or []) if t and t in text]
    if not terms:
        return [normal_fmt,text]
    pattern=re.compile("("+"|".join(re.escape(t) for t in sorted(terms,key=len,reverse=True))+")")
    parts=[]
    for piece in pattern.split(text):
        if not piece:
            continue
        parts.extend([bold_fmt if piece in terms else normal_fmt,piece])
    return parts


def _product_description_block(page, code):
    """
    Find the actual PDF text block containing the product title + technical
    description. This is safer than using the whole product row because prices,
    quantity and code are separate PDF blocks.
    """
    centers=_all_code_centers(page)
    current=[y for c,y in centers if c==code]
    if not current:
        return None
    y=current[0]

    ys=sorted(v for _,v in centers)
    prev=max([v for v in ys if v<y], default=y-140)
    nxt=min([v for v in ys if v>y], default=y+140)
    top=(prev+y)/2
    bottom=(y+nxt)/2

    candidates=[]
    for block in page.get_text('dict').get('blocks',[]):
        if 'lines' not in block:
            continue
        bbox=block.get('bbox',(0,0,0,0))
        cy=(bbox[1]+bbox[3])/2
        if not (top <= cy < bottom):
            continue

        text=' '.join(
            sp.get('text','')
            for line in block.get('lines',[])
            for sp in line.get('spans',[])
        )
        clean=clean_text(text)
        if not clean:
            continue

        score=0
        if 'gerotop' in clean.lower():
            score += 1000
        if '•' in clean:
            score += 500
        if ' typ ' in (' '+clean.lower()+' '):
            score += 300
        score += min(len(clean),500)
        # Description blocks are not narrow price/code cells.
        if bbox[2]-bbox[0] > 120:
            score += 200
        candidates.append((score,block))

    if not candidates:
        return None
    candidates.sort(key=lambda x:x[0],reverse=True)
    return candidates[0][1]


def _extract_title_and_rich_description(page, code, fallback_title='', fallback_details=''):
    """
    Read exactly the description block. Preserve PDF bold state span-by-span.
    """
    block=_product_description_block(page,code)
    if not block:
        return strip_brand(fallback_title), [{'text':fallback_details,'bold':False}] if fallback_details else []

    lines=[]
    for line in block.get('lines',[]):
        spans=[]
        for sp in line.get('spans',[]):
            txt=sp.get('text','')
            if not txt:
                continue
            font=(sp.get('font','') or '').lower()
            flags=int(sp.get('flags',0) or 0)
            bold=('bold' in font) or bool(flags & 16)
            spans.append({'text':txt,'bold':bold})
        if spans:
            lines.append(spans)

    if not lines:
        return strip_brand(fallback_title), [{'text':fallback_details,'bold':False}] if fallback_details else []

    # Entire consecutive bold block at the beginning is the title.
    title_parts=[]
    desc_start=None
    for li,line in enumerate(lines):
        line_text=clean_text(''.join(sp['text'] for sp in line))
        if not line_text:
            continue
        if line_text.startswith('•') or line_text.startswith('·'):
            desc_start=li
            break

        meaningful=[sp for sp in line if clean_text(sp['text'])]
        if meaningful and all(sp['bold'] for sp in meaningful):
            title_parts.append(line_text)
        else:
            # If this line starts with bold title and then normal text, keep
            # only its leading bold portion as title and begin description here.
            leading=[]
            for sp in meaningful:
                if sp['bold']:
                    leading.append(sp['text'])
                else:
                    break
            if leading and not title_parts:
                title_parts.append(clean_text(''.join(leading)))
            desc_start=li
            break

    title=clean_text(' '.join(title_parts)) if title_parts else clean_text(fallback_title)
    title=re.sub(r'(?i)^GEROtop\s*®?\s*','',title).strip()
    title=re.sub(r'^®\s*','',title).strip()

    rich=[]
    if desc_start is None:
        for li,line in enumerate(lines):
            line_text=clean_text(''.join(sp['text'] for sp in line))
            if line_text.startswith('•') or line_text.startswith('·'):
                desc_start=li
                break

    if desc_start is not None:
        for li in range(desc_start,len(lines)):
            line=lines[li]
            line_text=clean_text(''.join(sp['text'] for sp in line))
            if not line_text:
                continue
            # Never include pure numeric table content even if malformed PDF
            # accidentally placed it in a neighbouring block.
            if re.fullmatch(r'[\d\s.,%€Kč-]+',line_text):
                continue
            if rich:
                rich.append({'text':'\n','bold':False})
            for sp in line:
                txt=sp['text']
                if txt:
                    rich.append({'text':txt,'bold':bool(sp['bold'])})

    if not rich and fallback_details:
        rich=[{'text':fallback_details,'bold':False}]

    return title,rich



def _normalize_bullet_segments(segments):
    """
    Normalize rich technical text:
    - a new line starts only when a real bullet marker '•' starts a new bullet
    - wrapped PDF lines inside the same bullet are joined with a space
    - preserve each segment's bold/normal state
    """
    if not segments:
        return []

    # Flatten to logical tokens while retaining bold flags.
    tokens=[]
    for seg in segments:
        txt=str(seg.get('text','')).replace('\r','')
        bold=bool(seg.get('bold'))
        # Treat existing newlines as PDF line wraps, not necessarily logical lines.
        parts=txt.split('\n')
        for i,part in enumerate(parts):
            if part:
                tokens.append({'text':part,'bold':bold,'wrap_break':False})
            if i<len(parts)-1:
                tokens.append({'text':'','bold':False,'wrap_break':True})

    out=[]
    in_bullet=False
    pending_space=False

    for tok in tokens:
        if tok.get('wrap_break'):
            pending_space=True
            continue

        text=tok['text']
        bold=tok['bold']
        if not text:
            continue

        # Split multiple bullets if they somehow occur in one PDF span.
        chunks=re.split(r'(?=•)',text)
        for chunk in chunks:
            if not chunk:
                continue
            starts_bullet=chunk.startswith('•')

            if starts_bullet:
                if out and not str(out[-1].get('text','')).endswith('\n'):
                    out.append({'text':'\n','bold':False})
                pending_space=False
                in_bullet=True
                out.append({'text':chunk,'bold':bold})
                continue

            # Continuation of current logical line/bullet:
            # join PDF wrap with one space.
            if pending_space and out and not str(out[-1].get('text','')).endswith(('\n',' ')):
                out.append({'text':' ','bold':False})
            elif out and not str(out[-1].get('text','')).endswith(('\n',' ')) and not chunk.startswith((' ', ',', '.', ';', ':')):
                # Separate neighbouring spans on same line when PDF omitted spaces.
                out.append({'text':' ','bold':False})

            out.append({'text':chunk,'bold':bold})
            pending_space=False

    # Remove duplicate/leading/trailing newlines and spaces.
    clean=[]
    for seg in out:
        txt=seg['text']
        if txt=='\n':
            if not clean or clean[-1]['text']=='\n':
                continue
        clean.append(seg)

    while clean and clean[-1]['text'] in ('\n',' '):
        clean.pop()

    return clean


def _logical_description_lines(title,segments):
    """
    Estimate visual text lines in Excel after wrapping.
    Used only to choose row height, not to alter content.
    """
    lines=[title] if title else []
    current=''
    for seg in segments or []:
        txt=str(seg.get('text',''))
        for part in txt.split('\n'):
            if current:
                if part:
                    current += part
                lines.append(current)
                current=''
            else:
                current=part
    if current:
        lines.append(current)
    return [x for x in lines if x is not None]


def _estimate_row_height(title,segments,chars_per_line=56):
    """
    Calculate row height from final logical content.
    Approximate wrapped lines in merged B:G area with Calibri 11.
    """
    logical=_logical_description_lines(title,segments)
    visual=0
    for line in logical:
        text=str(line)
        # Every logical bullet/title needs at least one line.
        visual += max(1, math.ceil(max(len(text),1)/chars_per_line))
    # 15 pt per visual line + padding; keep sensible minimum.
    return max(54, 10 + visual*15)


def _rich_to_plain(segments):
    text=''.join(seg.get('text','') for seg in (segments or []))
    # Normalize bullet formatting while retaining line structure.
    text=text.replace('\r','')
    text=re.sub(r'\n{3,}','\n\n',text)
    return text.strip()


def _write_rich_cell(ws,row,col,title,segments,cell_fmt,bold_fmt,normal_fmt):
    """
    Title is always bold. Technical segments preserve their original bold state.
    """
    args=[bold_fmt,title]
    if segments:
        args += [normal_fmt,'\n']
        for seg in segments:
            txt=seg.get('text','')
            if not txt:
                continue
            args += [bold_fmt if seg.get('bold') else normal_fmt, txt]
    try:
        ws.write_rich_string(row,col,*args,cell_fmt)
    except Exception:
        plain=title
        if segments:
            plain += '\n' + ''.join(seg.get('text','') for seg in segments)
        ws.write(row,col,plain,cell_fmt)


def _build_details(raw_lines):
    bullets = []
    current = None
    for line in raw_lines:
        line = clean_text(line)
        if not line:
            continue
        if line.startswith('•'):
            if current:
                bullets.append(current)
            current = line[1:].strip()
        elif current is not None:
            current += ' ' + line
        else:
            # Text before the first bullet is not a technical bullet.
            continue
    if current:
        bullets.append(current)
    return bullets


def _parse_offer_number(joined):
    m=re.search(r"Nabídka číslo\s*([A-Z0-9-]+)",joined,re.I)
    if m:
        return m.group(1)
    m=re.search(r"ČÍSLO NÁVRHU\s*/\s*NABÍDKY\s*([A-Z0-9-]+)\s*/\s*(\d{4})",joined,re.I)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None

def _parse_date(joined):
    for p in [r"Datum vystavení\s*(\d{2}\.\d{2}\.\d{4})",r"DATUM VYPRACOVÁNÍ\s*(\d{2}\.\d{2}\.\d{4})"]:
        m=re.search(p,joined,re.I)
        if m:
            return m.group(1)
    return ""

def _parse_reference(joined):
    m=re.search(r"PRACOVNÍ NÁZEV AKCE\s+([^\n]+)",joined,re.I)
    if not m:
        return ""
    ref=clean_text(m.group(1))
    ref=re.split(r"\s+KONTAKTNÍ OSOBA\s+",ref,flags=re.I)[0]
    return ref.strip()

def _money_kc(s):
    return float(str(s).replace("Kč","").strip().replace(" ","").replace(",","."))

def parse_offer(pdf_path):
    doc=fitz.open(pdf_path)
    pages=[]
    all_lines=[]
    for page in doc:
        lines=[clean_text(x) for x in page.get_text("text").splitlines() if clean_text(x)]
        pages.append(lines)
        all_lines.extend(lines)
    joined="\n".join(all_lines)

    if not detect_pdf(pdf_path):
        raise ValueError("Dokument není rozpoznán jako cenová nabídka GEROtop / Prostupy.")

    offer_no=_parse_offer_number(joined)
    if not offer_no:
        raise ValueError("Nepodařilo se najít číslo nabídky GEROtop.")
    date=_parse_date(joined)
    reference=_parse_reference(joined)

    items=[]
    position=10
    for page_no,lines in enumerate(pages):
        code_idxs=[i for i,x in enumerate(lines) if CODE_RE.fullmatch(x)]
        for ci,i in enumerate(code_idxs):
            code=lines[i]
            j=code_idxs[ci+1] if ci+1<len(code_idxs) else len(lines)
            block=lines[i+1:j]

            title_line=next((x for x in block if x and not x.startswith("•")), "")
            title=strip_brand(title_line).strip()
            if not title or "Standardní doprava" in title:
                continue

            qty=None; original=None; disc=None; unit=None; total=None; qty_idx=None

            for k,line in enumerate(block):
                qm=QTY_RE.fullmatch(line)
                if qm:
                    qty_idx=k
                    qty=cz_num(qm.group(1))
                    money=[]; pcts=[]
                    for x in block[k+1:k+8]:
                        if PCT_RE.fullmatch(x):
                            pcts.append(cz_num(x.replace("%","")))
                        elif MONEY_LINE_RE.fullmatch(x):
                            money.append(cz_num(x))
                    if money: original=money[0]
                    if pcts:
                        disc=pcts[0]
                    else:
                        disc=_explicit_discount_for_row(doc[page_no],code)
                    if len(money)>=2: unit=money[1]
                    if len(money)>=3: total=money[2]
                    break

            if qty is None:
                for k in range(len(block)-2):
                    if re.fullmatch(r"\d+(?:[.,]\d+)?",block[k]) and re.fullmatch(r"\d[\d ]*\s*Kč",block[k+1],re.I) and re.fullmatch(r"\d[\d ]*(?:[.,]\d+)?\s*Kč",block[k+2],re.I):
                        qty_idx=k
                        qty=cz_num(block[k])
                        original=_money_kc(block[k+1])
                        unit=_money_kc(block[k+2])
                        disc=_explicit_discount_for_row(doc[page_no],code)
                        if disc is None:
                            disc=(1-unit/original)*100 if original else 0
                        total=unit*qty
                        break

            if qty is None or unit is None:
                continue

            pre=block[:qty_idx] if qty_idx is not None else block
            detail_lines=pre[1:]
            bullets=[]
            current=None
            for x in detail_lines:
                if x.startswith("•"):
                    if current:
                        bullets.append(current)
                    current=x[1:].strip()
                elif current is not None:
                    current += " " + x
            if current:
                bullets.append(current)
            details="\n".join("• "+b for b in bullets)

            if float(qty).is_integer():
                qty=int(qty)

            prev_code=lines[code_idxs[ci-1]] if ci>0 else None
            next_code=lines[code_idxs[ci+1]] if ci+1<len(code_idxs) else None
            image_bytes,image_ext=_render_row_product_images(
                doc,page_no,code,prev_code,next_code
            )

            title=clean_text(title).replace('\n',' ').strip()
            title=re.sub(r'(?i)^GER[O0]\s*TOP\w*\s*[®]?\s*','',title).strip()

            rich_title, rich_segments = _extract_title_and_rich_description(
                doc[page_no], code, fallback_title=title, fallback_details=details
            )
            if rich_title:
                title = rich_title
            rich_segments = _normalize_bullet_segments(rich_segments)
            details = _rich_to_plain(rich_segments) or details

            items.append({
                "position":position,"product":code,"description":title,"item_key":title,
                "details":details,"bullets":bullets,
                "rich_segments":rich_segments,
                "bold_terms":_bold_terms_for_row(doc[page_no],code),
                "quantity":qty,"unit":"KS",
                "original_unit_price":original,"discount_pct":disc or 0.0,
                "unit_price":unit,"item_total":total,
                "image_bytes":image_bytes,"image_ext":image_ext,
            })
            position += 10

    if not items:
        raise ValueError("V nabídce GEROtop nebyly nalezeny žádné produktové položky.")

    gross=sum(float((x["original_unit_price"] or x["unit_price"] or 0)*x["quantity"]) for x in items)
    net=sum(float(x["item_total"] or 0) for x in items)

    return {
        "supplier":"GEROtop","offer_no":offer_no,"date":date,"reference":reference,
        "gross":gross,"discount_pct":((gross-net)/gross*100 if gross else 0),
        "discount_value":net-gross,"net":net,"vat":None,"total":None,
        "source_pdf":os.path.basename(pdf_path),"source_type":"PDF","items":items,
    }


def _ocr_brand_present(text):
    """Tolerate OCR variants such as GEROtope / GER0top."""
    return bool(re.search(r'GER[O0]\s*TOP\w*', str(text), re.I))


def _ocr_price(text):
    m = re.search(r'(\d[\d .]*(?:[,.]\d+)?)\s*Kč', str(text), re.I)
    if not m:
        return None
    s = m.group(1).replace(' ', '').replace('.', '').replace(',', '.')
    try:
        return float(s)
    except Exception:
        return None


def _ocr_code(text):
    # Code is informational only. Normalize common OCR O->0 inside numeric code.
    s = str(text).upper()
    m = re.search(r'\b([0-9O]{3})\s*-\s*([0-9O]{2,4})\s*-\s*([0-9O]{2,4})\b', s)
    if not m:
        return ''
    return '-'.join(x.replace('O','0') for x in m.groups())


def parse_ocr_layout(payload, source_name='obrazek', fallback_date='', fallback_offer_no=''):
    """
    Parse Windows OCR JSON containing text lines WITH bounding rectangles.

    Geometry is essential for pasted e-mail quotations: plain OCR text often
    interleaves columns and rows. Here each GEROtop title defines one product
    row and prices are selected from the same vertical band.
    """
    if not isinstance(payload, dict):
        raise ValueError('Neplatná struktura OCR.')

    lines = payload.get('lines') or []
    full_text = payload.get('text') or ' '.join(str(x.get('text','')) for x in lines)

    if not (_ocr_brand_present(full_text) or
            re.search(r'(vložka|pažnice|tvarovka)\s+Typ', full_text, re.I)):
        raise ValueError('Obrázek nebyl rozpoznán jako nabídka GEROtop.')

    # Normalize and sort geometry.
    clean_lines = []
    for ln in lines:
        txt = clean_text(ln.get('text',''))
        if not txt:
            continue
        try:
            x = float(ln.get('x',0))
            y = float(ln.get('y',0))
            w = float(ln.get('w',0))
            h = float(ln.get('h',0))
        except Exception:
            continue
        clean_lines.append({'text':txt,'x':x,'y':y,'w':w,'h':h,'cy':y+h/2})
    clean_lines.sort(key=lambda a:(a['y'],a['x']))

    # Product title anchors. Brand may be slightly corrupted, so "Typ" +
    # characteristic product name is enough.
    anchors = []
    for ln in clean_lines:
        txt = ln['text']
        if (
            re.search(r'GER[O0]\s*TOP\w*', txt, re.I)
            or re.search(r'(vložka|pažnice|tvarovka).*\bTyp\b', txt, re.I)
        ):
            if re.search(r'\bTyp\b', txt, re.I):
                anchors.append(ln)

    # Deduplicate multiple OCR lines referring to the same vertical title.
    dedup = []
    for a in anchors:
        if not dedup or abs(a['cy'] - dedup[-1]['cy']) > 12:
            dedup.append(a)
        elif len(a['text']) > len(dedup[-1]['text']):
            dedup[-1] = a
    anchors = dedup

    if not anchors:
        raise ValueError('OCR nenašlo hlavní názvy produktových položek.')

    offer_no = ''
    m = re.search(r'(NA\s*0*\d{8,}(?:-\d+)?)', full_text, re.I)
    if m:
        offer_no = re.sub(r'\s+','',m.group(1))
    if not offer_no:
        m = re.search(r'([A-Z]\d{4,}[A-Z-]*)\s*/\s*(\d{4})', full_text, re.I)
        if m:
            offer_no = f'{m.group(1)}-{m.group(2)}'
    if not offer_no:
        offer_no = fallback_offer_no or ('OBRAZEK-' + re.sub(r'\W+','',source_name)[:28])

    dm = re.search(r'\b(\d{1,2}\.\d{1,2}\.\d{4})\b', full_text)
    date = dm.group(1) if dm else fallback_date

    items = []
    pos = 10

    for idx, anchor in enumerate(anchors):
        # Product band extends midway to adjacent product title anchors.
        if idx == 0:
            top = max(0, anchor['cy'] - 35)
        else:
            top = (anchors[idx-1]['cy'] + anchor['cy']) / 2

        if idx + 1 < len(anchors):
            bottom = (anchor['cy'] + anchors[idx+1]['cy']) / 2
        else:
            bottom = anchor['cy'] + 70

        band = [ln for ln in clean_lines if top <= ln['cy'] < bottom]
        if not band:
            continue

        title = strip_brand(anchor['text'])
        title = re.sub(r'^GER[O0]\s*TOP\w*\s*[®]?\s*', '', title, flags=re.I).strip()
        if not title:
            continue

        # If brand and title were split into adjacent OCR lines, enrich title.
        if not re.search(r'\bTyp\b', title, re.I):
            neighbours = sorted(band, key=lambda a:(abs(a['cy']-anchor['cy']),a['x']))
            for n in neighbours:
                if re.search(r'(vložka|pažnice|tvarovka).*\bTyp\b', n['text'], re.I):
                    title = re.sub(r'^GER[O0]\s*TOP\w*\s*[®]?\s*', '', n['text'], flags=re.I).strip()
                    break

        # Technical description = textual lines in the same band, excluding
        # the title and obvious numeric columns.
        detail_parts = []
        for ln in sorted(band,key=lambda a:(a['y'],a['x'])):
            txt = ln['text']
            if ln is anchor or txt == anchor['text']:
                continue
            if re.fullmatch(r'[\d O.-]{5,}', txt):
                continue
            if re.search(r'\d[\d .]*(?:[,.]\d+)?\s*Kč', txt, re.I):
                continue
            if re.search(r'\d+(?:[,.]\d+)?\s*%', txt):
                continue
            if re.fullmatch(r'\d+\s*(?:ks|kpl)?', txt, re.I):
                continue
            if re.search(r'Standardní doprava|balné', txt, re.I):
                continue
            if len(txt) > 3 and txt not in detail_parts:
                detail_parts.append(txt)

        # Code informational only.
        code = ''
        for ln in band:
            c = _ocr_code(ln['text'])
            if c:
                code = c
                break

        # Quantity: prefer token containing ks/kpl.
        qty = None
        for ln in band:
            qm = re.search(r'\b(\d+(?:[,.]\d+)?)\s*(ks|kpl)\b', ln['text'], re.I)
            if qm:
                qty = cz_num(qm.group(1))
                break

        # Currency values sorted LEFT->RIGHT. Standard GEROtop order is:
        # original unit, discounted unit, total.
        price_points = []
        for ln in band:
            for pm in re.finditer(r'(\d[\d .]*(?:[,.]\d+)?)\s*Kč', ln['text'], re.I):
                val = _ocr_price(pm.group(0))
                if val is not None:
                    price_points.append((ln['x'], ln['y'], val))
        price_points.sort(key=lambda p:(p[0],p[1]))

        # Deduplicate same OCR amount repeated in overlapping lines.
        compact = []
        for p in price_points:
            if not compact or abs(p[0]-compact[-1][0]) > 5 or abs(p[2]-compact[-1][2]) > 0.01:
                compact.append(p)
        prices = [p[2] for p in compact]

        discount = None
        for ln in band:
            pm = re.search(r'(\d+(?:[,.]\d+)?)\s*%', ln['text'])
            if pm:
                discount = cz_num(pm.group(1))
                break

        original = unit_price = item_total = None
        if len(prices) >= 3:
            original, unit_price, item_total = prices[0], prices[1], prices[-1]
        elif len(prices) == 2:
            original, unit_price = prices
        elif len(prices) == 1:
            unit_price = prices[0]

        # Quantity sometimes loses "ks". Derive from total/unit if possible,
        # otherwise take a small integer line to the left of price columns.
        if qty is None and item_total and unit_price:
            qcalc = item_total / unit_price
            if 0.5 <= qcalc <= 1000 and abs(qcalc-round(qcalc)) < 0.08:
                qty = int(round(qcalc))

        if qty is None:
            candidate_nums = []
            first_price_x = min((p[0] for p in compact), default=10**9)
            for ln in band:
                nm = re.fullmatch(r'\s*(\d{1,4})\s*',ln['text'])
                if nm and ln['x'] < first_price_x:
                    candidate_nums.append((ln['x'],int(nm.group(1))))
            if candidate_nums:
                qty = sorted(candidate_nums,key=lambda x:x[0])[-1][1]

        if original is None and unit_price is not None and discount is not None and discount < 100:
            original = unit_price / (1-discount/100)
        if discount is None and original and unit_price:
            discount = (1-unit_price/original)*100
        if item_total is None and qty is not None and unit_price is not None:
            item_total = qty * unit_price

        if qty is None or unit_price is None:
            continue

        if isinstance(qty,float) and qty.is_integer():
            qty = int(qty)

        # Filter transport rows.
        band_text = ' '.join(ln['text'] for ln in band)
        if re.search(r'Standardní doprava|doprava\s+a\s+balné',band_text,re.I):
            continue

        # Keep technical text readable; first title is never duplicated.
        details = []
        for d in detail_parts:
            d = strip_brand(d)
            if d and d != title and not d.startswith(title):
                details.append(d)
        details_text = '\n'.join(('• '+d.lstrip('•·- ').strip()) for d in details if d.strip())

        title=clean_text(title).replace('\n',' ').strip()
        title=re.sub(r'(?i)^GER[O0]\s*TOP\w*\s*[®]?\s*','',title).strip()

        items.append({
            'position':pos,
            'product':code,
            'description':title,
            'item_key':title,
            'details':details_text,
            'rich_segments':[{'text':details_text,'bold':False}] if details_text else [],
            'bullets':[d.lstrip('•·- ').strip() for d in details if d.strip()],
            'quantity':qty,
            'unit':'KS',
            'original_unit_price':original,
            'discount_pct':discount or 0.0,
            'unit_price':unit_price,
            'item_total':item_total,
            'image_bytes':None,
            'image_ext':None,
        })
        pos += 10

    if not items:
        raise ValueError('Z OCR rozložení se nepodařilo načíst žádné produktové položky.')

    gross = sum(float((i['original_unit_price'] or i['unit_price'] or 0) * i['quantity']) for i in items)
    net = sum(float(i['item_total'] or 0) for i in items)

    return {
        'supplier':'GEROtop',
        'offer_no':offer_no,
        'date':date,
        'reference':'',
        'gross':gross,
        'discount_pct':((gross-net)/gross*100.0) if gross else 0.0,
        'discount_value':net-gross,
        'net':net,
        'vat':None,
        'total':None,
        'source_pdf':source_name,
        'source_type':'OBRAZEK_EMAIL',
        'items':items,
    }


def parse_ocr_text(text, source_name='obrazek'):
    """
    Robust OCR parser for a GEROtop offer pasted as an image into an e-mail.
    Unlike the PDF parser it does not assume one logical field per OCR line.
    """
    raw = str(text or '').replace('\r', '\n')
    raw = re.sub(r'[ \t]+', ' ', raw)
    raw = re.sub(r'\n+', '\n', raw)
    upper = raw.upper()

    if 'GEROTOP' not in upper and 'PROSTUP' not in upper:
        raise ValueError('Obrázek nebyl rozpoznán jako nabídka GEROtop / Prostupy.')

    offer_match = re.search(r'(NA\s*0*\d{8,}(?:-\d+)?)', raw, re.I)
    if offer_match:
        offer_no = re.sub(r'\s+', '', offer_match.group(1))
    else:
        offer_no = 'OBRAZEK-' + re.sub(r'\W+', '', source_name)[:30]

    date_match = re.search(r'\b(\d{1,2}\.\d{1,2}\.\d{4})\b', raw)
    date = date_match.group(1) if date_match else ''

    # Normalize OCR confusions around product codes and percentages.
    normalized = raw.replace('–', '-').replace('—', '-')
    normalized = re.sub(r'(?<=\d)\s*-\s*(?=\d)', '-', normalized)

    # Product code is our anchor for finding item blocks, but NOT the unique DB key.
    code_matches = list(re.finditer(r'\b(\d{3}-\d{3}-\d{3})\b', normalized))
    items = []
    position = 10

    for idx, cm in enumerate(code_matches):
        code = cm.group(1)
        block_start = cm.end()
        block_end = code_matches[idx+1].start() if idx+1 < len(code_matches) else len(normalized)
        block = normalized[block_start:block_end]

        # Ignore transport / packing section even if OCR happens to invent a code-like token.
        if re.search(r'Standardn[ií]\s+doprava|doprava\s+a\s+baln[eé]|baln[eé]', block, re.I):
            continue

        # Find the quantity/currency tail. OCR may put everything on one line.
        # Expected order:
        # qty ks | original unit | discount % | discounted unit | total
        tail_re = re.compile(
            r'(?P<qty>\d+(?:[.,]\d+)?)\s*ks\b'
            r'.{0,120}?'
            r'(?P<orig>\d[\d .]*,\d{2})'
            r'.{0,80}?'
            r'(?P<disc>\d+(?:[.,]\d+)?)\s*%'
            r'.{0,80}?'
            r'(?P<unit>\d[\d .]*,\d{2})'
            r'.{0,80}?'
            r'(?P<total>\d[\d .]*,\d{2})',
            re.I | re.S
        )
        tm = tail_re.search(block)
        if not tm:
            # More tolerant fallback: collect values after an observed quantity.
            qm = re.search(r'(\d+(?:[.,]\d+)?)\s*ks\b', block, re.I)
            if not qm:
                continue
            qty = cz_num(qm.group(1))
            after = block[qm.end():qm.end()+400]
            pctm = re.search(r'(\d+(?:[.,]\d+)?)\s*%', after)
            money = re.findall(r'\d[\d .]*,\d{2}', after)
            if len(money) < 3:
                continue
            original_unit = cz_num(money[0])
            discount_pct = cz_num(pctm.group(1)) if pctm else 0.0
            unit_price = cz_num(money[-2])
            item_total = cz_num(money[-1])
            title_block = block[:qm.start()]
        else:
            qty = cz_num(tm.group('qty'))
            original_unit = cz_num(tm.group('orig'))
            discount_pct = cz_num(tm.group('disc'))
            unit_price = cz_num(tm.group('unit'))
            item_total = cz_num(tm.group('total'))
            title_block = block[:tm.start()]

        # Build title/details from OCR block.
        title_block = clean_text(title_block)
        title_block = strip_brand(title_block)

        # Common OCR rendering of bullets can be •, ·, -, or separated by line breaks.
        # Prefer the text before the first technical bullet.
        bullet_split = re.split(r'\s*[•·]\s*|\s+-\s+(?=[A-Za-zÁ-ž])', title_block, maxsplit=1)
        title = bullet_split[0].strip(' :-')
        if not title:
            continue

        # Avoid swallowing column headings into the title.
        title = re.sub(
            r'^(Obr[aá]zek|K[oó]d|N[aá]zev|Jednotka|Jednotkov[aá]\s+cena|Sleva)\s+',
            '',
            title,
            flags=re.I
        ).strip()

        details = ''
        bullets = []
        # Use remaining pre-price text as technical detail if available.
        remainder = title_block[len(bullet_split[0]):].strip()
        if remainder:
            raw_parts = re.split(r'[•·]|\s+-\s+(?=[A-Za-zÁ-ž])', remainder)
            bullets = [clean_text(x).strip(' -:') for x in raw_parts if clean_text(x).strip(' -:')]
            details = '\n'.join('• ' + b for b in bullets)

        if float(qty).is_integer():
            qty = int(qty)

        title=clean_text(title).replace('\n',' ').strip()
        title=re.sub(r'(?i)^GER[O0]\s*TOP\w*\s*[®]?\s*','',title).strip()

        items.append({
            'position': position,
            'product': code,
            'description': title,
            'item_key': title,
            'details': details,
            'rich_segments':[{'text':details,'bold':False}] if details else [],
            'bullets': bullets,
            'quantity': qty,
            'unit': 'KS',
            'original_unit_price': original_unit,
            'discount_pct': discount_pct,
            'unit_price': unit_price,
            'item_total': item_total,
            'image_bytes': None,
            'image_ext': None,
        })
        position += 10

    if not items:
        raise ValueError('Z obrazové nabídky se nepodařilo načíst žádné produktové položky.')

    net = sum(float(x['item_total'] or 0) for x in items)
    gross = sum(
        float((x['original_unit_price'] or x['unit_price'] or 0) * x['quantity'])
        for x in items
    )

    return {
        'supplier': 'GEROtop',
        'offer_no': offer_no,
        'date': date,
        'reference': '',
        'gross': gross,
        'discount_pct': ((gross-net)/gross*100.0) if gross else 0.0,
        'discount_value': net-gross,
        'net': net,
        'vat': None,
        'total': None,
        'source_pdf': source_name,
        'source_type': 'OBRAZEK_EMAIL',
        'items': items,
    }



def export_excel(data, output_path, price_alerts=None):
    wb = xlsxwriter.Workbook(output_path)
    ws = wb.add_worksheet('Nabídka')

    title_fmt = wb.add_format({'font_name':'Calibri','bold':True,'font_size':16,'font_color':'#1F4E78'})
    label_fmt = wb.add_format({'font_name':'Calibri','bold':True,'bg_color':'#D9EAF7','border':1})
    value_fmt = wb.add_format({'font_name':'Calibri','border':1})
    money_fmt = wb.add_format({'font_name':'Calibri','border':1,'num_format':'#,##0.00 "Kč"'})
    header_fmt = wb.add_format({'font_name':'Calibri',
        'bold':True,'font_color':'white','bg_color':'#1F4E78',
        'border':1,'align':'center','valign':'vcenter','text_wrap':True
    })
    text_fmt = wb.add_format({'font_name':'Calibri','border':1,'valign':'vcenter','align':'left','text_wrap':True})
    bold_inline = wb.add_format({'font_name':'Calibri','bold':True})
    normal_inline = wb.add_format({'font_name':'Calibri',})
    int_fmt = wb.add_format({'font_name':'Calibri','border':1,'num_format':'#,##0','valign':'vcenter','align':'center'})
    item_money = wb.add_format({'font_name':'Calibri','border':1,'num_format':'#,##0.00 "Kč"','valign':'vcenter','align':'center'})
    key_money = wb.add_format({'font_name':'Calibri',
        'border':1,'num_format':'#,##0.00 "Kč"',
        'valign':'vcenter','align':'center','bold':True
    })
    pct_fmt = wb.add_format({'font_name':'Calibri','border':1,'num_format':'0.##" %"','valign':'vcenter','align':'center'})
    alert_text = wb.add_format({'font_name':'Calibri','border':1,'valign':'vcenter','align':'left','text_wrap':True,'bg_color':'#F4CCCC'})
    alert_int = wb.add_format({'font_name':'Calibri','border':1,'num_format':'#,##0','valign':'vcenter','align':'center','bg_color':'#F4CCCC'})
    alert_money = wb.add_format({'font_name':'Calibri','border':1,'num_format':'#,##0.00 "Kč"','valign':'vcenter','bg_color':'#F4CCCC'})
    alert_key_money = wb.add_format({'font_name':'Calibri','border':1,'num_format':'#,##0.00 "Kč"','valign':'vcenter','bold':True,'bg_color':'#F4CCCC'})
    alert_pct = wb.add_format({'font_name':'Calibri','border':1,'num_format':'0.##" %"','valign':'vcenter','align':'center','bg_color':'#F4CCCC'})

    ws.write('A1', f'Cenová nabídka {data["offer_no"]}', title_fmt)
    summary = [
        ('Dodavatel', data.get('supplier','GEROtop')),
        ('Číslo nabídky', data['offer_no']),
        ('Datum', data.get('date','')),
        ('Zakázka', data.get('reference','') or 'Nepřiřazeno'),
        ('Celkem bez DPH – pouze výrobky', data.get('net')),
    ]
    for r,(lab,val) in enumerate(summary, start=2):
        ws.write(r-1,0,lab,label_fmt)
        if isinstance(val,(int,float)):
            ws.write_number(r-1,1,val,money_fmt)
        else:
            ws.write(r-1,1,val,value_fmt)

    # Layout:
    # A = code
    # B:E = merged rich product description (4 columns)
    # F:G = merged image area (2 columns)
    # H = quantity
    # I = discounted unit price (most important)
    # J = discount
    # K = original unit price
    # L = total
    start = 9
    ws.write(start-1,0,'Kód',header_fmt)
    ws.merge_range(start-1,1,start-1,4,'Název / technický popis',header_fmt)
    ws.merge_range(start-1,5,start-1,6,'Obrázek',header_fmt)
    ws.write(start-1,7,'Počet [KS]',header_fmt)
    ws.write(start-1,8,'Cena/ks po slevě',header_fmt)
    ws.write(start-1,9,'Sleva',header_fmt)
    ws.write(start-1,10,'Původní cena/ks',header_fmt)
    ws.write(start-1,11,'Cena celkem',header_fmt)

    alert_positions = {a.get('position') for a in (price_alerts or [])}

    for row,item in enumerate(data['items'], start=start):
        is_alert = item['position'] in alert_positions
        tf = alert_text if is_alert else text_fmt
        inf = alert_int if is_alert else int_fmt
        mf = alert_money if is_alert else item_money
        kmf = alert_key_money if is_alert else key_money
        pf = alert_pct if is_alert else pct_fmt

        ws.write(row,0,item.get('product',''),tf)
        # Format the whole merged description range first. This is needed
        # for Excel to honor vertical centering with rich text.
        ws.merge_range(row,1,row,4,'',tf)
        for cc in range(1,5):
            ws.write_blank(row,cc,None,tf)

        details = item.get('details','')
        rich_segments = _normalize_bullet_segments(item.get('rich_segments') or [])
        if not rich_segments and details:
            rich_segments=[{'text':details,'bold':False}]
        _write_rich_cell(
            ws,row,1,item.get('description',''),rich_segments,tf,bold_inline,normal_inline
        )

        # The picture belongs to H of the same item row. With object_position=1
        # it moves and sizes with cells; offsets keep it visually inside H.
        ws.merge_range(row,5,row,6,'',tf)
        ws.write_number(row,7,float(item.get('quantity') or 0),inf)
        ws.write_number(row,8,float(item.get('unit_price') or 0),kmf)
        ws.write_number(row,9,float(item.get('discount_pct') or 0),pf)
        ws.write_number(row,10,float(item.get('original_unit_price') or 0),mf)
        ws.write_number(row,11,float(item.get('item_total') or 0),mf)

        row_h = _estimate_row_height(
            item.get('description',''),
            rich_segments,
            chars_per_line=56
        )
        ws.set_row(row, row_h)

        img = item.get('image_bytes')
        if img:
            try:
                # Column H is about 18 characters wide; choose a row-aware target ratio.
                # This keeps the product centered while maximizing usable area.
                target_ratio=max(0.70,min(1.35,120.0/max(row_h,1)))
                centered_img,centered_ext=_center_for_excel_cell(
                    img,item.get('image_ext') or 'png',target_ratio=target_ratio
                )
                image_data=io.BytesIO(centered_img)
                # embed_image is XlsxWriter's "Place in Cell" implementation.
                # Excel owns the picture as the content of H for this item row.
                ws.embed_image(
                    row,5,'produkt.'+centered_ext,
                    {'image_data':image_data}
                )
            except Exception:
                # Compatibility fallback for an unusually old XlsxWriter.
                try:
                    image_data=io.BytesIO(img)
                    ws.insert_image(
                        row,5,'produkt.'+(item.get('image_ext') or 'png'),
                        {'image_data':image_data,'object_position':1}
                    )
                except Exception:
                    pass

    ws.set_column('A:A',16)
    ws.set_column('B:E',11)
    ws.set_column('F:G',18)
    ws.set_column('H:H',12)
    ws.set_column('I:I',20)
    ws.set_column('J:J',11)
    ws.set_column('K:K',19)
    ws.set_column('L:L',19)
    ws.freeze_panes(start,0)
    ws.set_landscape()
    ws.fit_to_pages(1,0)

    if data.get('source_type') == 'OBRAZEK_EMAIL':
        src = wb.add_worksheet('Zdroj - obrázek')
        src.write('A1','Nabídka byla rozpoznána z obrázku vloženého do e-mailu. Doporučena vizuální kontrola.', title_fmt)

    wb.close()

def process_file(pdf_path, output_path=None, price_alerts=None):
    data = parse_offer(pdf_path)
    if output_path is None:
        output_path = str(Path(pdf_path).with_name(f'Extrakce dat CN {data["offer_no"]}.xlsx'))
    export_excel(data, output_path, price_alerts=price_alerts)
    return data, output_path
