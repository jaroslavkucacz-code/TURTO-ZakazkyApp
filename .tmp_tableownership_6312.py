from pathlib import Path
import re

# post_baseline: one final pipeline.
p = Path('post_baseline.py')
s = p.read_text(encoding='utf-8')
if '    from datetime import datetime\n' not in s:
    s = s.replace(
        '    from pathlib import Path\n',
        '    from pathlib import Path\n    from datetime import datetime\n',
        1,
    )
start = s.index('    def schedule_final_layout(app):')
end_marker = '    M.schedule_final_tree_layout = schedule_final_layout\n'
end = s.index(end_marker, start) + len(end_marker)
replacement = '''    def parse_table_date(value):
        text = str(value or '').strip()
        for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d.%m.%y'):
            try:
                return datetime.strptime(text, fmt)
            except Exception:
                pass
        return datetime.min

    def reset_default_sort_state(tree):
        try:
            tree._sort_state = {}
            tree._active_sort = None
        except Exception:
            pass

    def sort_default_date(tree, candidates):
        if tree is None:
            return
        try:
            cols = list(tree.cget('columns'))
            col = next((name for name in candidates if name in cols), None)
            if not col:
                return
            rows = [
                (parse_table_date(tree.set(iid, col)), iid)
                for iid in tree.get_children('')
            ]
            rows.sort(key=lambda item: item[0], reverse=True)
            for position, (_value, iid) in enumerate(rows):
                tree.move(iid, '', position)
            reset_default_sort_state(tree)
        except Exception:
            pass

    def sort_default_alpha(tree, candidates):
        if tree is None:
            return
        try:
            cols = list(tree.cget('columns'))
            col = next((name for name in candidates if name in cols), None)
            if not col:
                return
            key = getattr(
                M,
                'czech_sort_key',
                lambda value: str(value or '').strip().casefold(),
            )
            rows = list(tree.get_children(''))
            rows.sort(key=lambda iid: key(tree.set(iid, col)))
            for position, iid in enumerate(rows):
                tree.move(iid, '', position)
            reset_default_sort_state(tree)
        except Exception:
            pass

    def apply_default_table_sort(app):
        sort_default_date(
            getattr(app, 'action_tree', None),
            ('Přijato', 'Datum přijetí', 'Přijetí'),
        )
        sort_default_date(
            getattr(app, 'request_tree', None),
            ('Poptáno', 'Datum poptávky', 'Poptávka'),
        )
        sort_default_date(
            getattr(app, 'mivo_tree', None),
            ('Poptáno', 'Datum poptávky', 'Poptávka'),
        )
        sort_default_alpha(
            getattr(app, 'project_tree', None),
            ('Název Akce', 'Název akce', 'Akce', 'Název'),
        )

    def finalize_main_tables(app):
        contract = getattr(M, 'apply_main_table_contract', None)
        if callable(contract):
            try:
                contract(app)
            except Exception:
                pass
        apply_default_table_sort(app)
        normalize(app)
        recolor_dashboard(app)
        try:
            walk(
                app,
                lambda widget: schedule_auxiliary_redraw(widget)
                if widget.winfo_class() == 'Treeview'
                else None,
            )
        except Exception:
            pass

    M.finalize_main_tables = finalize_main_tables

    def schedule_final_layout(app):
        """Debounce refreshes into one deterministic final table phase."""
        try:
            previous = getattr(app, '_turto_final_layout_after', None)
            if previous is not None:
                try:
                    app.after_cancel(previous)
                except Exception:
                    pass

            def finish():
                try:
                    app._turto_final_layout_after = None
                except Exception:
                    pass
                finalize_main_tables(app)

            app._turto_final_layout_after = app.after_idle(finish)
        except Exception:
            finalize_main_tables(app)

    M.schedule_final_tree_layout = schedule_final_layout
'''
s = s[:start] + replacement + s[end:]
p.write_text(s, encoding='utf-8')

# v638: semantic contract only, no delayed wrappers/binding removal.
p = Path('ZakazkyApp_base_6.1/v638_table_updatefix.py')
s = p.read_text(encoding='utf-8')
s = s.replace(
    '# TURTO CRM 6.0.38 - stable tables, correct Action sorting, manual update notes',
    '# TURTO CRM compatibility - main-table contract + manual update notes',
    1,
)
old_heading = '''    def _heading_contract(app,tree,cols):
        if tree is None:return
        try:
            tree.configure(show='headings',columns=cols)
            for c in cols:
                tree.heading(c,text=c,command=lambda col=c,t=tree:app.sort_tree(t,col))
        except Exception:pass
'''
new_heading = '''    def _heading_contract(app, tree, cols):
        if tree is None:
            return
        try:
            current = tuple(tree.cget('columns'))
            if current != tuple(cols):
                tree.configure(show='headings', columns=cols)
            else:
                tree.configure(show='headings')
            for col in cols:
                tree.heading(
                    col,
                    text=col,
                    command=lambda name=col, current_tree=tree: app.sort_tree(
                        current_tree,
                        name,
                    ),
                )
        except Exception:
            pass
'''
if old_heading not in s:
    raise SystemExit('v638 heading contract block not found')
s = s.replace(old_heading, new_heading, 1)
s = re.sub(
    r"\n    def _sort_projects_default\(app\):.*?(?=\n    def _style_urgent_requests\(app\):)",
    '\n',
    s,
    count=1,
    flags=re.S,
)
s = re.sub(
    r"\n    def _remove_problematic_request_bindings\(app\):.*?(?=\n    def _stabilize\(app,sort_projects=False\):)",
    '\n',
    s,
    count=1,
    flags=re.S,
)
contract_start = s.index('    def _stabilize(app,sort_projects=False):')
manual_marker = '    # ------------------------------------------------------------------\n    # MANUAL UPDATE CHECK:'
contract_end = s.index(manual_marker, contract_start)
contract = '''    def apply_main_table_contract(app):
        """Set final columns/counts/styles; scheduling belongs to post_baseline."""
        _restore_main_tables(app)
        _style_urgent_requests(app)

    M.apply_main_table_contract = apply_main_table_contract

'''
s = s[:contract_start] + contract + s[contract_end:]
s = re.sub(
    r"\n    old_init=M\.App\.__init__\n    def init\(self,\*a,\*\*k\):.*?\n    M\.App\.__init__=init\s*$",
    '\n',
    s,
    count=1,
    flags=re.S,
)
p.write_text(s, encoding='utf-8')

# v637: data model/detail only, no main-table refresh wrappers.
p = Path('ZakazkyApp_base_6.1/v637_project_offer_model.py')
s = p.read_text(encoding='utf-8')
section_start = s.index(
    '    # ACTIONS(projects) MAIN TABLE: show offers here, remove from Opportunities.'
)
section_start = s.rfind('    # ------------------------------------------------------------------', 0, section_start)
next_title = s.index('    # REAL ACTION DETAIL (ProjectDialog): related offers.', section_start)
section_end = s.rfind('    # ------------------------------------------------------------------', section_start, next_title)
replacement = '''    # ------------------------------------------------------------------
    # MAIN TABLE OWNERSHIP
    # Columns and offer counts are finalized by post_baseline via v638 contract.
    # This module owns only the offer-link data model and related detail UI.
    # ------------------------------------------------------------------

'''
s = s[:section_start] + replacement + s[section_end:]
p.write_text(s, encoding='utf-8')

# v632: context/link owner only, no visible count/column refresh overlay.
p = Path('ZakazkyApp_base_6.1/v632_offerlinks.py')
s = p.read_text(encoding='utf-8')
helper_start = s.index('    def _add_offer_column(tree):')
helper_end = s.index('    def _open_action_offers(app):', helper_start)
s = s[:helper_start] + '    # Visible offer-count columns are owned by the central table contract.\n\n' + s[helper_end:]
refresh_start = s.index('    # Recompute visible counts after normal refreshes.')
init_start = s.index('    old_init=M.App.__init__', refresh_start)
s = s[:refresh_start] + s[init_start:]
old_init = '''    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        def later():
            _refresh_counts(self)
            _install_context(self,getattr(self,'action_tree',None),'action')
            _install_context(self,getattr(self,'request_tree',None),'request')
        try:self.after(1800,later)
        except Exception:pass
        return r
    M.App.__init__=init
'''
new_init = '''    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        def later():
            _install_context(self,getattr(self,'action_tree',None),'action')
            _install_context(self,getattr(self,'request_tree',None),'request')
        try:self.after_idle(later)
        except Exception:pass
        return r
    M.App.__init__=init
'''
if old_init not in s:
    raise SystemExit('v632 init block not found')
s = s.replace(old_init, new_init, 1)
p.write_text(s, encoding='utf-8')

# v644: import-compatible no-op; sorting moved to post_baseline.
Path('ZakazkyApp_base_6.1/v644_default_date_sort.py').write_text(
    '# TURTO CRM compatibility stub.\n'
    '# Default table sorting moved into the single post_baseline finalizer.\n\n'
    'def apply(M):\n'
    '    return None\n',
    encoding='utf-8',
)

Path('release_version.txt').write_text('6.3.12\n', encoding='utf-8')
Path('release_notes.txt').write_text(
    '• Hlavní tabulky mají jeden finální mechanismus v post_baseline: kontrakt sloupců/počtů → výchozí řazení → roztažení šířek → pomocné překreslení.\n'
    '• Odstraněny opožděné zásahy v638 po 50/420 ms, které po změně stavu tabulku znovu přestavěly a vytvářely bílý prostor napravo.\n'
    '• v638 už pouze poskytuje sémantický kontrakt tabulek; neobaluje refresh_*, neplánuje časované stabilizace a neodpojuje Configure/scroll bindingy.\n'
    '• v637 už po after_idle nemanipuluje hlavními sloupci/počty; zůstává vlastníkem datového modelu nabídka → poptávka → Akce a detailů.\n'
    '• v632 už nepřidává ani nepřepočítává sloupec Nabídky po refreshi; zachovává vazby a řádkové kontextové menu, které se na záhlaví neotevře.\n'
    '• Výchozí řazení z v644 bylo přesunuto do stejné finální fáze; v644 je nyní pouze kompatibilní no-op stub.\n'
    '• Zachováno je hromadné DB-only mazání nabídek, Excel exporty, databázové schéma a Outlook MSG/PDF drag & drop.\n',
    encoding='utf-8',
)

# Static regression checks.
base = Path('post_baseline.py').read_text(encoding='utf-8')
v632 = Path('ZakazkyApp_base_6.1/v632_offerlinks.py').read_text(encoding='utf-8')
v637 = Path('ZakazkyApp_base_6.1/v637_project_offer_model.py').read_text(encoding='utf-8')
v638 = Path('ZakazkyApp_base_6.1/v638_table_updatefix.py').read_text(encoding='utf-8')
v644 = Path('ZakazkyApp_base_6.1/v644_default_date_sort.py').read_text(encoding='utf-8')
assert 'def finalize_main_tables' in base
assert 'def apply_default_table_sort' in base
final = base.split('def finalize_main_tables', 1)[1].split('M.finalize_main_tables', 1)[0]
assert final.index('contract(app)') < final.index('apply_default_table_sort(app)') < final.index('normalize(app)')
assert 'M.apply_main_table_contract = apply_main_table_contract' in v638
assert 'for ms in (50,420)' not in v638
assert '_remove_problematic_request_bindings' not in v638
assert "t.unbind('<Configure>')" not in v638
assert "for name in ('refresh_requests','refresh_actions','refresh_projects','refresh_all')" not in v638
assert '_remove_offer_col_from_opportunities' not in v637
assert '_add_project_offer_column' not in v637
assert "for name in ('refresh_actions','refresh_projects','refresh_all')" not in v637
assert '_refresh_counts' not in v632
assert '_add_offer_column' not in v632
assert "identify_region(e.x, e.y) != 'cell'" in v632
assert 'refresh_actions' not in v644
assert 'after_idle' not in v644
assert 'return None' in v644
assert Path('release_version.txt').read_text(encoding='utf-8').strip() == '6.3.12'
