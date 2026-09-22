"""Small-window settings and native, copyable corporate PDF regression checks."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ZakazkyApp_base_6.1'))
OUTPUT = REPO / 'build/validation/settings-vector'


def fixture(name):
    spec = importlib.util.spec_from_file_location(name, REPO / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pdf_checks(td):
    import fitz
    from price_lists_domain.issued_offers import corporate_renderer, template_layout, template_settings, schema
    from v710_cleanup import group_offer_items
    previous = fixture('validate-7900-corporate-templates')
    M = previous.owner(td)
    previous.foundation(M)
    schema.ensure_business_documents_schema(M)
    M.group_issued_offer_items = group_offer_items
    doc, items = template_settings.sample_offer()
    doc.update(document_number='CN26-UKÁZKA', issuer_contact_snapshot='Jiří Cír',
               issuer_phone_snapshot='123456789', issuer_email_snapshot='ukazka@example.test')
    template = template_layout.builtin_template()
    for name, changes in (('standard', {}), ('wide', dict(margin_left_mm=5, margin_right_mm=5)),
                          ('narrow', dict(margin_left_mm=32, margin_right_mm=32)),
                          ('tall', dict(header_height_mm=40)), ('short', dict(header_height_mm=12))):
        current = dict(template, **changes)
        target = OUTPUT / (name + '.pdf')
        corporate_renderer.render(M, doc, items, current, target)
        with fitz.open(target) as pdf:
            page = pdf[0]
            text = ' '.join(page.get_text().split()).replace('\u2010', '-')
            for value in ('CENOVÁ NABÍDKA', 'CN26-UKÁZKA', 'Jiří Cír', 'ukazka@example.test',
                          'Kaprova 42/14', 'Masarykova 234/30', '268 01 Hořovice', 'DIČ: CZ24196231',
                          'Prodejní sklad', 'Po – Čt: 7:30 – 15:30', 'Pá: 8:30 – 15:00',
                          'Akustická kapsa – provedení A', '1 476,00 Kč/ks'):
                assert value in text, (name, value, text)
            assert not page.get_images(), 'Stationery must contain paths and actual text, no bitmap'
            assert all(span['type'] == 0 for span in page.get_texttrace()), 'Invisible OCR overlay'
            left = current['margin_left_mm'] * corporate_renderer.MM
            right = corporate_renderer.WIDTH - current['margin_right_mm'] * corporate_renderer.MM
            bands = [d['rect'] for d in page.get_drawings() if d['fill'] and d['rect'].y0 < 100 and d['rect'].width > 200]
            assert len(bands) >= 2
            assert all(abs(b.x0-left) < .01 and abs(b.x1-right) < .01 for b in bands[:2]), (name, bands)
            for span in page.get_texttrace():
                r = fitz.Rect(span['bbox'])
                assert r.x0 >= left - 1 and r.x1 <= right + 1 and r.y0 >= 0 and r.y1 <= page.rect.height, (name, r)
            if name == 'standard':
                page.get_pixmap(matrix=fitz.Matrix(1.7, 1.7)).save(OUTPUT / 'pdf-page.png')
                page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=fitz.Rect(left, 7, right, 75)).save(OUTPUT / 'pdf-header.png')
    # Multi-page output and custom hours remain actual visible text on each page.
    current = copy.deepcopy(template)
    style = template_layout.normalize(current['layout_json'])
    style.update(edit_opening_hours=True, opening_hours='Pondělí: 8:00 – 16:00\nPátek: 8:30 – 14:00')
    current['layout_json'] = json.dumps(style)
    corporate_renderer.render(M, doc, items * 16, current, OUTPUT / 'multipage.pdf')
    with fitz.open(OUTPUT / 'multipage.pdf') as pdf:
        assert len(pdf) > 1
        for page in pdf:
            text = ' '.join(page.get_text().split()).replace('\u2010', '-')
            assert text.count('CENOVÁ NABÍDKA') == 1 and 'CN26-UKÁZKA' in text
            assert 'Pondělí: 8:00 – 16:00' in text and 'Pátek: 8:30 – 14:00' in text
            assert not page.get_images()
    print('PDF: selectable Czech text, native artwork, exact margins, varied header dimensions and repeated pages OK', flush=True)


def ui_checks(td):
    previous = fixture('validate-834-user-access')
    M, settle = previous.prepare(td)
    M.APP_VERSION = (REPO / 'build/windows/version.txt').read_text().strip()
    errors = []
    M.messagebox.showwarning = lambda *a, **k: errors.append(a)
    M.messagebox.showerror = lambda *a, **k: errors.append(a)
    M.App.maybe_show_morning_overview = lambda self: None
    root = M.App()
    root.report_callback_exception = lambda *e: errors.append(str(e))
    from PIL import ImageGrab
    try:
        root.active_user.set('ADMIN')
        root.refresh_user_access()
        root.minsize(700, 450)
        root.show_page('settings')
        settle(root, 1)
        for geometry, theme in (('900x620+0+0', 'Světlý'), ('740x520+0+0', 'Tmavý'), ('1450x900+0+0', 'Světlý')):
            root.apply_theme(theme, False)
            root.state('normal')
            root.geometry(geometry)
            settle(root, .3)
            assert root.winfo_width() == int(geometry.split('x')[0]), root.geometry()
            for index, (key, section) in enumerate(root._settings_sections.items()):
                root._settings_notebook.select(index)
                settle(root, .3)
                widgets = list(section.walk(section.body))
                buttons = [w for w in widgets if w.winfo_class() in ('TButton', 'TEntry', 'TCombobox')]
                assert buttons, key
                for widget in buttons:
                    assert widget.winfo_rootx() >= section.canvas.winfo_rootx(), (key, widget)
                    assert widget.winfo_rootx()+widget.winfo_width() <= section.canvas.winfo_rootx()+section.canvas.winfo_width()+1, (key, widget)
                    if str(widget.cget('state')) == 'disabled':
                        continue
                    section.canvas.yview_moveto(0)
                    widget.focus_force()
                    settle(root, .04)
                    assert widget.winfo_rooty() >= section.canvas.winfo_rooty()-1, (key, widget, 'top')
                    assert widget.winfo_rooty()+widget.winfo_height() <= section.canvas.winfo_rooty()+section.canvas.winfo_height()+1, (key, widget, 'bottom')
                section.canvas.yview_moveto(0)
                settle(root, .1)
                if section.body.winfo_height() > section.canvas.winfo_height():
                    buttons[0].event_generate('<MouseWheel>', delta=-120)
                    settle(root, .1)
                    assert section.canvas.yview()[0] > 0, ('Wheel over child did not scroll', key, geometry, buttons[0].bindtags(), section.canvas.yview())
                section.canvas.yview_moveto(0)
                settle(root, .1)
                if not geometry.startswith('1450'):
                    suffix = '-dark' if theme == 'Tmavý' else ''
                    ImageGrab.grab(window=root.winfo_id()).save(OUTPUT / ('settings-' + key + suffix + '.png'))
        # Every original settings action is still represented, including the old hidden last card.
        all_text = [str(w.cget('text')) for s in root._settings_sections.values() for w in s.walk(s.body) if w.winfo_class() in ('TButton', 'TLabel')]
        for caption in ('Spravovat uživatele…', 'Spravovat číselníky…', 'Ukládání zpracovaných nabídek',
                        'Trvalý archiv Ceníků', 'Optimalizovat databázi', 'Obnovení předchozí verze'):
            assert caption in all_text, caption
        assert not errors, errors
        print('Settings: all sections and controls reachable at 740/900/1450 px, local wheel, keyboard focus and both themes OK', flush=True)
    finally:
        root.destroy()


if __name__ == '__main__':
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if '--worker' in sys.argv:
        (ui_checks if '--ui' in sys.argv else pdf_checks)(sys.argv[-1])
    else:
        with tempfile.TemporaryDirectory(prefix='turto-settings-vector-') as td:
            subprocess.run([sys.executable, '-B', __file__, *sys.argv[1:], '--worker', td], check=True, timeout=120)
