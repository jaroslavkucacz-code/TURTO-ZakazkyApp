#!/usr/bin/env python3
"""Real Windows: badge input routing, viewport bounds, themes and live dialogs."""
import os
from pathlib import Path
import sys
import tempfile
import time
from datetime import date, timedelta

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ZakazkyApp_base_6.1'))


def settle(root, seconds=.25):
    until = time.monotonic()+seconds
    while time.monotonic() < until:
        root.update()
        time.sleep(.01)


def run(td):
    os.environ['TURTO_CRM_DATA_ROOT'] = td
    os.environ['LOCALAPPDATA'] = str(Path(td)/'local')
    os.environ['TURTO_DISABLE_AUTO_UPDATE'] = '1'
    import app
    import data_location
    import runtime_bootstrap
    from price_lists_domain.platform.calm_theme_820 import install_tree
    from PIL import ImageGrab
    data_location.apply_to_app(app)
    app.ensure_schema()
    runtime_bootstrap.apply_all(app)
    app.APP_VERSION = (REPO/'build/windows/version.txt').read_text().strip()
    app.ensure_schema()
    app.ensure_test_user()
    app.App.maybe_show_morning_overview = lambda self: None
    app.messagebox.showinfo = lambda *a, **k: None
    app.messagebox.showwarning = lambda *a, **k: None
    root = app.App()
    errors = []
    root.report_callback_exception = lambda *exc: errors.append(str(exc))
    output = REPO/'dist/branding-preview'
    output.mkdir(parents=True, exist_ok=True)

    def screenshot(name):
        ImageGrab.grab(bbox=(root.winfo_rootx(),root.winfo_rooty(),
            root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height()), all_screens=True).save(output/name)

    try:
        root.state('normal')
        root.geometry('1240x840+0+0')
        settle(root, 4)
        root.apply_theme('Světlý')
        root.show_page('actions')
        settle(root)
        tree = root.action_tree
        cols = tuple(tree.cget('columns'))
        fixtures = [('BD Zenklova','Rozpracováno','SDMStav Praha s.r.o.'),
                    ('RD Osek','Rozpracováno','Milan Piskaček'),
                    ('Stadion Semily','Rozpracováno','MBQ s.r.o.'),
                    ('VIVUS Kolbenova IV','Rozpracováno','STRABAG a.s.'),
                    ('Sedlec A','Připraveno','V.D.O. Group s.r.o.'),
                    ('Nádrž Slavoňov','Hotovo','BAUFERA s.r.o.'),
                    ('YARD Hrdlořezy','Rozpracováno','ROLAND monolity s.r.o.')]
        fixture_ids = []
        with app.db() as con:
            for i,(project,status,company) in enumerate(fixtures):
                cid = con.execute('INSERT INTO companies(short_name,official_name) VALUES(?,?)', (company,company)).lastrowid
                aid = con.execute('INSERT INTO actions(name,company_id,created_date,deadline,status) VALUES(?,?,?,?,?)',
                    (project,cid,'2099-09-16','2020-01-01' if i==3 else '',status)).lastrowid
                fixture_ids.append('a'+str(aid))
        root.refresh_actions()
        settle(root)
        for name in ('Světlý','Tmavý'):
            root.apply_theme(name)
            settle(root)
            deco = tree._turto_cells_820
            assert any(c=='Stav' for _,c,_,_ in deco.rendered), deco.rendered
            assert (fixture_ids[3],'Deadline','late') in [r[:3] for r in deco.rendered], deco.rendered
            assert tree.tag_configure('status_active')['background'] == ''
            style = app.ttk.Style(root)
            assert style.lookup('Accent.TButton','foreground',('active',)).upper() == '#FFFFFF'
            assert style.lookup('Topbar.TLabel','foreground').upper() == '#263442'
            screenshot('theme-820-'+('light' if name=='Světlý' else 'dark')+'.png')

        # A dedicated table isolates native selection/context/double-click input
        # from business callbacks while using the real installed presentation.
        win = app.tk.Toplevel(root)
        t = app.ttk.Treeview(win, columns=('Stav','Deadline','Název'), show='headings', selectmode='extended')
        t.pack(fill='both',expand=True)
        for col in t.cget('columns'):
            t.heading(col,text=col)
            t.column(col,width=180,stretch=False)
        for i in range(2000):
            t.insert('','end',iid=str(i),values=('Hotovo' if i==1 else 'Rozpracováno','01.01.2020','Záznam '+str(i)),tags=('status_active',))
        t.set('2', 'Deadline', (date.today()+timedelta(days=1)).isoformat())
        t.item('2', tags=('status_active','v770_deadline_attention'))
        settle(root)
        install_tree(t)
        settle(root)
        d = t._turto_cells_820
        assert len(d.canvases) < 100, len(d.canvases)
        assert not any(i=='1' and c=='Deadline' for i,c,_,_ in d.rendered), d.rendered
        assert ('2','Deadline','wait') in [r[:3] for r in d.rendered], d.rendered
        original = tuple(t.item('0','values'))
        double, context = [], []
        t.bind('<Double-Button-1>',lambda e: double.append(t.identify_row(e.y)))
        t.bind('<Button-3>',lambda e: context.append(t.identify_row(e.y)))
        # Real OS clicks verify the routed events still produce native double clicks.
        import win32api
        import win32con
        canvas = d.canvases[0]
        point = (canvas.winfo_rootx()+25,canvas.winfo_rooty()+10)
        win32api.SetCursorPos(point)
        for _ in range(2):
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN,0,0,0,0)
            settle(root,.025)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP,0,0,0,0)
            settle(root,.025)
        assert t.selection() == ('0',), t.selection()
        assert double == ['0'], double
        win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN,0,0,0,0)
        win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP,0,0,0,0)
        settle(root)
        assert context == ['0'], context
        # Scrollbar/programmatic and mouse-wheel changes must track actual rows.
        t.yview_moveto(.5)
        settle(root)
        assert int(d.rendered[0][0]) > 500, d.rendered[:2]
        before = t.yview()[0]
        c = d.canvases[0]
        c.event_generate('<MouseWheel>',delta=-120,x=10,y=10,rootx=c.winfo_rootx()+10,rooty=c.winfo_rooty()+10)
        settle(root)
        assert t.yview()[0] > before
        t.configure(displaycolumns=('Název','Deadline'))
        settle(root)
        assert all(c!='Stav' for _,c,_,_ in d.rendered)
        t.configure(displaycolumns=('Název','Deadline','Stav'))
        t.column('Název',width=1200)
        t.xview_moveto(1)
        settle(root)
        for c, record in zip(d.canvases,d.rendered):
            iid,col,_,_ = record
            x,y,w,h = t.bbox(iid,col)
            assert abs(int(c.place_info()['x'])-max(1,x+1)) <= 1
        t.set('0','Stav','Připraveno')
        t.yview_moveto(0)
        settle(root)
        assert tuple(t.item('0','values')) == ('Připraveno',)+original[1:]
        assert any(i=='0' and kind=='ready' for i,c,kind,_ in d.rendered)
        # Idle work is finite and destruction cancels pending decoration.
        count = d.draw_count
        settle(root,.4)
        assert d.draw_count == count, (count,d.draw_count)
        d.schedule()
        win.destroy()
        settle(root)
        assert d.pending is None
        root.apply_theme('Světlý')
        dialog = app.ActionDialog(root)
        settle(root)
        screenshot('theme-820-dialog.png')
        dialog.destroy()
        assert not errors, errors
        print('8.0.20: both themes, actual cell badges, 2000-row viewport, native double/context clicks, wheel, hide/reorder/resize, mutation, idle and destruction OK', flush=True)
    finally:
        root._turto_closing = True
        root.destroy()


if __name__ == '__main__':
    if sys.platform == 'win32':
        with tempfile.TemporaryDirectory(prefix='turto-theme-820-',ignore_cleanup_errors=True) as td:
            run(td)
