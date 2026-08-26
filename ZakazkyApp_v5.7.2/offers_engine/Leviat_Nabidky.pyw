import os, re, sys, traceback
from pathlib import Path

try:
    import fitz  # PyMuPDF
    import xlsxwriter
except ImportError as e:
    if __name__ == '__main__':
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk(); root.withdraw()
            messagebox.showerror('Chybí knihovna', f'Chybí potřebná knihovna: {e}\n\nSpusťte program přes START.bat.')
        except Exception:
            pass
    raise

MONEY_RE = re.compile(r'(?<!\d)(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})(?!\d)')
PRODUCT_RE = re.compile(r'^\d{8,12}$')
POSITION_RE = re.compile(r'^\d{1,4}$')
QTY_RE = re.compile(r'^\d{1,3}(?:\.\d{3})*$|^\d+$')

TECH_PREFIXES = (
    'Celní kód', 'KS', '/1 KS', 'DPH', 'Země ', 'CZK', 'Pol.', 'Č. výrobku',
    'Popis výr.', 'Množství', 'Cena v', 'Čistá částka', 'Částka', 'Sleva',
    'Přirážka/Sleva', 'Leviat s.r.o.', 'Pekařská ', 'Česká republika', 'T:', 'E:', 'DIČ'
)


def cz_number(s: str) -> float:
    s = s.strip().replace(' ', '').replace('.', '').replace(',', '.')
    return float(s)


def parse_qty(s: str) -> float:
    s = s.strip().replace(' ', '').replace('.', '')
    return float(s)


def money_tokens(line: str):
    vals = []
    for m in MONEY_RE.finditer(line):
        vals.append(cz_number(m.group(0)))
    return vals


def clean_lines(pdf_path: str):
    doc = fitz.open(pdf_path)
    lines = []
    for page in doc:
        for raw in page.get_text('text').splitlines():
            t = ' '.join(raw.strip().split())
            if t:
                lines.append(t)
    return lines


def find_value_after(lines, label, max_ahead=3):
    for i, line in enumerate(lines):
        if line == label or line.startswith(label):
            same = line[len(label):].strip()
            if same:
                return same
            for j in range(i+1, min(i+1+max_ahead, len(lines))):
                if lines[j]: return lines[j]
    return ''


def parse_offer(pdf_path: str):
    lines = clean_lines(pdf_path)
    joined = '\n'.join(lines)

    offer_match = re.search(r'Nabídka\s+(\d+)', joined)
    if not offer_match:
        raise ValueError('V PDF se nepodařilo najít číslo nabídky.')
    offer_no = offer_match.group(1)

    # Datum bývá na samostatném řádku po štítku Datum.
    date = ''
    for i, line in enumerate(lines):
        if line == 'Datum':
            for cand in lines[i+1:i+4]:
                if re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', cand):
                    date = cand; break
            if date: break
    if not date:
        m = re.search(r'\b(\d{2}\.\d{2}\.\d{4})\b', joined)
        date = m.group(1) if m else ''

    # Reference zákazníka: první netechnický řádek po štítku.
    reference = ''
    for i, line in enumerate(lines):
        if line.startswith('Reference zákazníka'):
            same = line.replace('Reference zákazníka','',1).strip()
            if same:
                reference = same
            else:
                for cand in lines[i+1:i+4]:
                    if cand not in ('Leviat kontakt', 'Kontaktní osoba'):
                        reference = cand; break
            break

    items = []
    i = 0
    while i < len(lines) - 3:
        # položka = číslo pozice + následující číslo výrobku
        if POSITION_RE.fullmatch(lines[i]) and PRODUCT_RE.fullmatch(lines[i+1]):
            position = int(lines[i])
            product = lines[i+1]
            start_desc = i + 2

            qty_idx = None
            unit_price = None
            item_total = None
            customs_idx = None

            # Konec položky může být "Celní kód", ale některé položky jej
            # vůbec nemají. Proto zároveň hlídáme začátek další položky.
            next_item_idx = None
            for k in range(start_desc, min(start_desc + 30, len(lines) - 1)):
                if POSITION_RE.fullmatch(lines[k]) and PRODUCT_RE.fullmatch(lines[k+1]):
                    next_item_idx = k
                    break

            for k in range(start_desc, min(start_desc + 30, len(lines))):
                if lines[k].startswith('Celní kód'):
                    customs_idx = k
                    break

            boundaries = [x for x in (customs_idx, next_item_idx) if x is not None]
            item_end = min(boundaries) if boundaries else min(start_desc + 20, len(lines))

            # Množství identifikujeme tak, že po něm bezprostředně následují
            # alespoň dvě cenové hodnoty. Bereme jen souvislý cenový blok,
            # aby se do ceny položky omylem nezapočítala následná DPH.
            for k in range(start_desc, item_end):
                if QTY_RE.fullmatch(lines[k]):
                    vals = []
                    q = k + 1
                    while q < item_end:
                        mv = money_tokens(lines[q])
                        if mv:
                            vals.extend(mv)
                            q += 1
                            continue
                        break
                    if len(vals) >= 2:
                        qty_idx = k
                        unit_price = vals[0]
                        item_total = vals[-1]
                        break
            if qty_idx is None:
                i += 1; continue

            desc_parts = lines[start_desc:qty_idx]
            # pokračování názvu po cenách a před koncem položky
            for q in range(qty_idx+1, item_end):
                if not money_tokens(lines[q]) and not lines[q].startswith(TECH_PREFIXES):
                    desc_parts.append(lines[q])
            description = ' '.join(desc_parts).strip()
            qty = parse_qty(lines[qty_idx])
            if qty.is_integer(): qty = int(qty)

            items.append({
                'position': position,
                'product': product,
                'description': description,
                'quantity': qty,
                'unit': 'KS',
                'unit_price': unit_price,
                'item_total': item_total,
            })
            if next_item_idx is not None and item_end == next_item_idx:
                i = next_item_idx
            else:
                i = item_end + 1
        else:
            i += 1

    if not items:
        raise ValueError('V nabídce se nepodařilo najít žádné položky.')

    def summary_money(label):
        # Leviat často tiskne popisek a částku na dva samostatné textové řádky.
        for idx, line in enumerate(lines):
            if label.lower() in line.lower():
                vals = money_tokens(line)
                # u řádků s procentem nechceme zaměnit např. 21,00 % za částku
                if vals and '%' not in line:
                    return vals[-1]
                for nxt in lines[idx+1:idx+4]:
                    vals = money_tokens(nxt)
                    if vals and '%' not in nxt:
                        return vals[-1]
        return None

    gross = summary_money('Celková čistá částka')
    net = summary_money('Celkem bez DPH')
    total = summary_money('Celková částka nabídky')

    vat = None
    for idx, line in enumerate(lines):
        if line.startswith('DPH ') and '%' in line:
            for nxt in lines[idx+1:idx+3]:
                vals = money_tokens(nxt)
                if vals:
                    vat = vals[-1]
                    break
            if vat is not None:
                break

    discount_pct = 0.0
    discount_value = 0.0
    for idx, line in enumerate(lines):
        if 'sleva' in line.lower() and '%' in line:
            pm = re.search(r'(\d+(?:,\d+)?)\s*%', line)
            if pm:
                discount_pct = cz_number(pm.group(1))
            # částka slevy bývá na následujícím řádku
            for nxt in lines[idx+1:idx+3]:
                vals = money_tokens(nxt)
                if vals:
                    discount_value = -abs(vals[-1])
                    break
            break

    return {
        'offer_no': offer_no,
        'date': date,
        'reference': reference,
        'items': items,
        'gross': gross,
        'discount_pct': discount_pct,
        'discount_value': discount_value,
        'net': net,
        'vat': vat,
        'total': total,
        'source_pdf': os.path.basename(pdf_path),
    }


def export_excel(data, output_path, price_alerts=None):
    wb = xlsxwriter.Workbook(output_path)
    ws = wb.add_worksheet('Nabídka')

    fmt_title = wb.add_format({'bold': True, 'font_size': 16, 'font_color': '#1F4E78'})
    fmt_label = wb.add_format({'bold': True, 'bg_color': '#D9EAF7', 'border': 1})
    fmt_value = wb.add_format({'border': 1})
    fmt_money = wb.add_format({'num_format': '#,##0.00 "Kč"', 'border': 1})
    fmt_pct = wb.add_format({'num_format': '0.00" %"', 'border': 1})
    fmt_header = wb.add_format({'bold': True, 'font_color': 'white', 'bg_color': '#1F4E78', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
    fmt_text = wb.add_format({'border': 1, 'valign': 'top'})
    fmt_blank_name = wb.add_format({'border': 1, 'valign': 'top'})
    fmt_int = wb.add_format({'border': 1, 'num_format': '#,##0', 'valign': 'top'})
    fmt_item_money = wb.add_format({'border': 1, 'num_format': '#,##0.00 "Kč"', 'valign': 'top'})
    fmt_alert_text = wb.add_format({'border': 1, 'valign': 'top', 'bg_color': '#F4CCCC'})
    fmt_alert_int = wb.add_format({'border': 1, 'num_format': '#,##0', 'valign': 'top', 'bg_color': '#F4CCCC'})
    fmt_alert_money = wb.add_format({'border': 1, 'num_format': '#,##0.00 "Kč"', 'valign': 'top', 'bg_color': '#F4CCCC'})

    ws.write('A1', f'Cenová nabídka {data["offer_no"]}', fmt_title)
    summary = [
        ('Číslo nabídky', data['offer_no'], fmt_value),
        ('Datum', data['date'], fmt_value),
        ('Reference / zakázka', data['reference'], fmt_value),
        ('Součet položek před slevou', data['gross'], fmt_money),
        ('Sleva %', data['discount_pct'], fmt_pct),
        ('Sleva Kč', data['discount_value'], fmt_money),
        ('Celkem bez DPH', data['net'], fmt_money),
        ('DPH', data['vat'], fmt_money),
        ('Celková částka s DPH', data['total'], fmt_money),
    ]
    for r, (label, value, valfmt) in enumerate(summary, start=2):
        ws.write(r-1, 0, label, fmt_label)
        if value is None:
            ws.write_blank(r-1, 1, None, fmt_value)
        else:
            ws.write(r-1, 1, value, valfmt)

    if price_alerts:
        alert_fmt = wb.add_format({'bold': True, 'font_color': '#9C0006', 'bg_color': '#FFC7CE'})
        ws.write('D2', 'UPOZORNĚNÍ NA CENY', alert_fmt)
        ws.write('D3', f'Položek nad limitem: {len(price_alerts)}', alert_fmt)

    # Položková tabulka. Název položky je skutečně sloučen přes 6 sloupců C:H.
    # Jednotka KS se neopakuje v řádcích; je uvedena přímo v záhlaví množství.
    start = 13
    ws.write(start-1, 0, 'Pol.', fmt_header)
    ws.write(start-1, 1, 'Číslo výrobku', fmt_header)
    ws.merge_range(start-1, 2, start-1, 7, 'Název položky', fmt_header)
    ws.write(start-1, 8, 'Množství [KS]', fmt_header)
    ws.write(start-1, 9, 'Cena za kus bez DPH', fmt_header)
    ws.write(start-1, 10, 'Cena položky bez DPH', fmt_header)

    alert_positions = {a.get('position') for a in (price_alerts or [])}

    for r, item in enumerate(data['items'], start=start):
        is_alert = item['position'] in alert_positions
        f_int = fmt_alert_int if is_alert else fmt_int
        f_text = fmt_alert_text if is_alert else fmt_text
        f_money = fmt_alert_money if is_alert else fmt_item_money

        ws.write_number(r, 0, item['position'], f_int)
        ws.write_string(r, 1, item['product'], f_text)
        ws.merge_range(r, 2, r, 7, item['description'], f_text)
        ws.write_number(r, 8, item['quantity'], f_int)
        ws.write_number(r, 9, item['unit_price'], f_money)
        ws.write_number(r, 10, item['item_total'], f_money)

    lastrow = start + len(data['items']) - 1
    ws.autofilter(start-1, 0, lastrow, 10)
    ws.freeze_panes(start, 0)
    ws.set_column('A:A', 9)
    ws.set_column('B:B', 17)
    # Šest sloupců C:H tvoří jeden sloučený blok názvu.
    ws.set_column('C:H', 10)
    ws.set_column('I:I', 15)
    ws.set_column('J:K', 22)
    ws.set_row(start-1, 32)
    ws.set_landscape()
    ws.fit_to_pages(1, 0)
    wb.close()

def process_file(pdf_path, output_path=None):
    data = parse_offer(pdf_path)
    if output_path is None:
        output_path = str(Path(pdf_path).with_name(f'Extrakce dat CN {data["offer_no"]}.xlsx'))
    export_excel(data, output_path)
    return data, output_path


def gui_main():
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.title('Leviat - převod cenové nabídky do Excelu')
    root.geometry('560x260')
    root.resizable(False, False)

    tk.Label(root, text='Leviat - PDF nabídka → Excel', font=('Segoe UI', 16, 'bold')).pack(pady=(24,8))
    tk.Label(root, text='Vyberte jednu cenovou nabídku PDF.\nProgram projde všechny její stránky a vytvoří samostatný Excel.', font=('Segoe UI', 10), justify='center').pack(pady=5)

    status = tk.StringVar(value='Připraveno')

    def choose():
        path = filedialog.askopenfilename(title='Vyberte PDF cenovou nabídku', filetypes=[('PDF soubory','*.pdf')])
        if not path: return
        status.set('Zpracovávám nabídku...')
        root.update_idletasks()
        try:
            data, out = process_file(path)
            status.set(f'Hotovo: {os.path.basename(out)}')
            messagebox.showinfo('Hotovo', f'Nabídka {data["offer_no"]} byla zpracována.\n\nPoložek: {len(data["items"])}\nExcel: {out}')
        except Exception as e:
            status.set('Chyba při zpracování')
            messagebox.showerror('Chyba', f'PDF se nepodařilo zpracovat:\n\n{e}\n\nPokud jde o nový formát nabídky, pošlete PDF k úpravě parseru.')

    tk.Button(root, text='VYBRAT PDF A VYTVOŘIT EXCEL', command=choose, font=('Segoe UI', 11, 'bold'), width=32, height=2).pack(pady=18)
    tk.Label(root, textvariable=status, font=('Segoe UI', 9), fg='#444444').pack()
    tk.Label(root, text='Výsledný Excel se uloží do stejné složky jako PDF.', font=('Segoe UI', 9), fg='#666666').pack(pady=8)
    root.mainloop()


if __name__ == '__main__':
    if len(sys.argv) >= 2:
        # Režim přetažení PDF na START.bat. Výstup se vždy uloží vedle PDF.
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        try:
            pdf = sys.argv[1]
            data, out = process_file(pdf)
            messagebox.showinfo(
                'Leviat Exporter - hotovo',
                f'Nabídka {data["offer_no"]} byla zpracována.\n\n'
                f'Položek: {len(data["items"])}\n'
                f'Excel uložen do stejné složky jako PDF:\n{out}'
            )
        except Exception as e:
            messagebox.showerror('Leviat Exporter - chyba', f'PDF se nepodařilo zpracovat:\n\n{e}')
        finally:
            root.destroy()
    else:
        gui_main()
