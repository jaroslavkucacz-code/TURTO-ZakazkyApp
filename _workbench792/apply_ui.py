from pathlib import Path
root=Path.cwd();src=root/'ZakazkyApp_base_6.1'
def change(path,old,new,n=1):
    text=path.read_text(encoding='utf-8');assert text.count(old)==n,(path.name,text.count(old),old[:80]);path.write_text(text.replace(old,new),encoding='utf-8')
p=src/'v770_runtime_policy.py'
change(p,'def _place_dialog(win: Any, parent: Any = None, preferred: tuple[int, int] | None = None) -> None:\n    try:\n        if bool(win.overrideredirect()):\n            return\n    except Exception:\n        pass', '''def _place_dialog(win: Any, parent: Any = None, preferred: tuple[int, int] | None = None) -> None:
    from dialog_chrome import is_maximized, prepare_dialog
    try:
        if not win.winfo_exists() or bool(win.overrideredirect()):
            return
        prepare_dialog(win)
        if is_maximized(win):
            return
    except Exception:
        return''')
change(p,'        win.maxsize(max(360, area_w - 10), max(220, area_h - 10))', '''        # Allow the entire work area on maximize, including native frame bounds.
        win.maxsize(max(360, area_w + 32), max(220, area_h + 32))''')
change(p,'            previous_init(self, *args, **kwargs)\n            for delay in (20, 140, 260):', '''            previous_init(self, *args, **kwargs)
            from dialog_chrome import prepare_dialog
            def mapped(event):
                if event.widget is self:
                    self.after_idle(lambda: prepare_dialog(self))
            self.bind("<Map>", mapped, add="+")
            for delay in (20, 140, 260):''')
p=src/'v638_table_updatefix.py'
change(p,"tree.heading(c,text=c,command=lambda col=c,t=tree:app.sort_tree(t,col))", "tree.heading(c,text=c,anchor=tree.column(c,'anchor'),command=lambda col=c,t=tree:app.sort_tree(t,col))")
change(p,'            _heading_contract(app,pt,PROJECT_COLS)', '''            # A delayed legacy pass must not remove the current activity column.
            cols=PROJECT_COLS
            if 'Poslední pohyb' in pt.cget('columns'):
                cols=(*PROJECT_COLS,'Poslední pohyb')
            _heading_contract(app,pt,cols)''')
p=src/'v644_default_date_sort.py'
change(p,'    "dash_tasks_tree",','    "dash_tasks_tree",\n    "dash_requests_tree",')
change(p,'    for tree in _known_trees(app):\n        for attribute in ("_sync_filter_bar", "_date_cell_redraw"):', '''    for tree in _known_trees(app):
        # Older delayed column-contract changes recreate headings with Tk's
        # default centre anchor. Keep the row anchor authoritative here, in the
        # existing bounded redraw owner (never a global Treeview hook or scan).
        try:
            for column in tree.cget("columns"):
                anchor = str(tree.column(column, "anchor"))
                if str(tree.heading(column, "anchor")) != anchor:
                    tree.heading(column, anchor=anchor)
        except Exception:
            pass
        for attribute in ("_sync_filter_bar", "_date_cell_redraw"):''')
p=src/'price_lists_domain/platform/commercial_workspace.py'
change(p,'tree.heading(column, text=column, command=lambda col=column: sorter(tree, col))','tree.heading(column, text=column, anchor=anchors.get(column, "w"), command=lambda col=column: sorter(tree, col))')
change(p,'            tree.heading(column, text=column)\n        tree.column(','            tree.heading(column, text=column, anchor=anchors.get(column, "w"))\n        tree.column(')
change(p,'app.price_taxonomy_tree.heading("Cen", text="Cen")','app.price_taxonomy_tree.heading("Cen", text="Cen", anchor="e")')
p=root/'scripts/validate-real-ui.py'
change(p,'    sys.path.insert(0, str(repository))', '''    # Only post_baseline is shipped from root. Root historical module copies
    # must not shadow the current canonical source in this runtime regression.
    import importlib.util
    spec = importlib.util.spec_from_file_location('post_baseline', repository/'post_baseline.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules['post_baseline'] = module
    spec.loader.exec_module(module)''')
s=p.read_text(encoding='utf-8');start=s.index('    # Match the generated ZakazkyCRM.pyw layer order.');end=s.index('    # Run the fully wrapped schema owner',start)
s=s[:start]+'''    # Exercise exactly the bootstrap shipped by the current launcher, including
    # the stability bridge and final dialog/filter policy, not a pre-7.7 subset.
    import runtime_bootstrap
    runtime_bootstrap.apply_all(app)

'''+s[end:];p.write_text(s,encoding='utf-8')
change(p,'        assert bool(getattr(root.request_tree, "_v760_requests_resize_guard", False))\n        assert bool(getattr(root.mivo_tree, "_v760_mivo_resize_guard", False))', '''        # These obsolete Configure->full-refresh guards were deliberately
        # disabled by the 7.7 stability bridge. The shipped bootstrap must keep
        # them disabled; responsive navigation below tests their replacement.
        assert app._turto_v762_reentrant_table_refresh_disabled
        assert not getattr(root.request_tree, "_v760_requests_resize_guard", False)
        assert not getattr(root.mivo_tree, "_v760_mivo_resize_guard", False)''')
p=root/'scripts/validate-7600-table-activity-performance.py'
change(p,'assert "v760_table_activity_performance.apply(app)" in real_ui','assert "runtime_bootstrap.apply_all(app)" in real_ui')
p=root/'scripts/publish-update.sh'
change(p,'rm -rf "$STAGE"', '''command -v xvfb-run >/dev/null || (sudo apt-get update -qq && sudo apt-get install -y -qq xvfb)
timeout 160s xvfb-run -a -s '-screen 0 1920x1080x24' python scripts/validate-792-customer-output.py "$BASE_DIR"

rm -rf "$STAGE"''')
change(p,'  runtime_bootstrap.py ', '  runtime_bootstrap.py dialog_chrome.py ')
change(p,'test -e "$RUNTIME/v770_runtime_policy.py"','test -e "$RUNTIME/v770_runtime_policy.py"\ntest -e "$RUNTIME/dialog_chrome.py"\ntest -e "$RUNTIME/price_lists_domain/issued_offers/customer_text.py"')
(root/'release_version.txt').write_text('7.9.2\n',encoding='utf-8')
(root/'release_notes.txt').write_text('''• Opraven únik označené zdrojové/nákupní ceny z převzatých popisů do zákaznických nabídek. Ochrana se používá při převzetí, načtení staršího konceptu, uložení a vykreslení PDF. Technické údaje i interní ceny zůstávají zachované.
• Starší PDF s rozpoznaným interním cenovým údajem se nesmí znovu použít k odeslání. U konceptu vytvořte nové PDF; u uzamčené nabídky použijte kopii. Původní archiv se nepřepisuje.
• Filtry se přizpůsobují skutečné výšce popisků a polí; přestanou se smršťovat na nízký proužek. Zachováno bezpečné časování bez vnořeného překreslování Tk.
• Běžné dialogy mají na Windows maximalizační tlačítko. Odložené centrování již nezmenšuje maximalizované okno. Našeptávače a rozbalovací okna jsou z této úpravy vynechány.
• Číslo nabídky je u původní grafiky TURTO přímo ve volné části červeného záhlaví. Duplicitní nadpis a číslo níže zmizely; datum zůstává. Logo ani původní grafické soubory se nemění.
• Vlastní šablona má záložku Záhlaví a zápatí s volbou čísla v horním pruhu a editovatelnou otevírací dobou (nejvýše 4 řádky). Prázdný text ji skryje; vypnutí volby vrátí původní podobu. Nastavení přežije export/import šablony.
• Nákup, marže a zisk nadále zůstávají interní. Aktualizace nemění zdrojové nabídky, cenotvorbu, vlastní šablony ani historická PDF. Zachována záloha databáze a vratné programové aktualizace.
• Sjednocení záhlaví s řádky tabulek bez globálních zásahů do Tk. Opraveno také pozdní přepsání sloupce Poslední pohyb ve starší vrstvě Akcí.
''',encoding='utf-8')
print('UI, bootstrap tests and release changes applied')
