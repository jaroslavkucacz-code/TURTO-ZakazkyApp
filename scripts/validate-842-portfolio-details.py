#!/usr/bin/env python3
"""Real Treeview gestures, context targets and read-only directory details."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('fixture841',REPO/'scripts/validate-841-centers-contacts.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
from price_lists_domain.platform import user_access as access
from price_lists_domain.platform.calm_theme_820 import palette
sql=fixture.sql


def ui_checks(td):
    M,settle,d=fixture.prepare(td)
    M.APP_VERSION=(REPO/'build/windows/version.txt').read_text().strip()
    sql(M,"UPDATE companies SET official_name='842 Ukázková společnost',short_name='842 Ukázková' WHERE id=?",(d['cid'],))
    sql(M,"UPDATE companies SET official_name='842 Další společnost',short_name='842 Další' WHERE id=?",(d['other'],))
    sql(M,"UPDATE people SET name='Anna Veselá',email='anna@example.test',phone='123456789' WHERE id=?",(d['pid'],))
    for name,email in [('Jan Novák','jan@example.test'),('Petra Svobodová','petra@example.test')]:
        sql(M,"INSERT INTO people(name,email,phone,company_id) VALUES(?,?,'123456789',?)",(name,email,d['cid']))
    errors=[];M.messagebox.showwarning=lambda *a,**k:errors.append(a)
    M.messagebox.showerror=lambda *a,**k:errors.append(a)
    M.messagebox.showinfo=lambda *a,**k:None
    M.App.maybe_show_morning_overview=lambda self:None
    M.App.report_callback_exception=lambda self,*a:errors.append(str(a))
    root=M.App();root.report_callback_exception=lambda *a:errors.append(str(a))
    output=REPO/'build/validation/portfolio-842';output.mkdir(parents=True,exist_ok=True)
    def shot(name):
        if '--no-screenshots' in sys.argv:return
        from PIL import ImageGrab
        settle(root,.15)
        ImageGrab.grab(bbox=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height())).save(output/name)
    try:
        root.active_user.set('ADMIN');root.refresh_user_access()
        root.state('normal');root.geometry('1450x850+0+0');root.apply_theme('Světlý');root.show_page('portfolio');settle(root,1)
        w=root.portfolio_workspace;t=w.tree;cid=f"c{d['cid']}";pid=f"p{d['pid']}"
        w.query.set('842');w.selection.set('Všichni obchodníci');w.refresh();settle(root)
        # Search now expands matches; start collapsed to exercise the arrow gesture.
        t.item(cid,open=False);settle(root)
        print('842: portfolio ready',flush=True)
        def coords(iid,column='Společnost / kontakt'):
            t.see(iid);settle(root,.05);x,y,width,height=t.bbox(iid,column)
            return x+min(width//2,80),y+height//2
        # Native indicator click is the only mouse gesture that expands.
        _,cy=coords(cid)
        arrow=next(x for x in range(35) if 'indicator' in t.identify_element(x,cy))
        t.event_generate('<ButtonPress-1>',x=arrow,y=cy,time=1000)
        t.event_generate('<ButtonRelease-1>',x=arrow,y=cy,time=1010);settle(root)
        assert t.item(cid,'open') and t.bbox(pid)
        assert 'portfolio_company' in t.item(cid,'tags') and 'portfolio_person' in t.item(pid,'tags')
        assert t.set(pid,'Společnost / kontakt').startswith('\u2003\u2003↳')
        assert str(t.tag_configure('portfolio_company','background'))==palette(t)['head']
        assert w.company_font.actual('weight')=='bold'
        shot('portfolio-hierarchy-light.png')
        root.apply_theme('Tmavý');settle(root)
        assert str(t.tag_configure('portfolio_company','background'))==palette(t)['head']
        shot('portfolio-hierarchy-dark.png');root.apply_theme('Světlý');settle(root)
        print('842: hierarchy and themes ready',flush=True)
        def detail(iid,expected_class,attribute,value,timestamp):
            seen=[]
            def close():
                windows=[x for x in root.winfo_children() if isinstance(x,expected_class)]
                print('842: closing detail',iid,len(windows),flush=True)
                for win in windows:
                    seen.append(getattr(win,attribute));win.destroy()
            root.after(700,close)
            x,y=coords(iid);t.focus_force()
            for press in (timestamp,timestamp+100):
                t.event_generate('<ButtonPress-1>',x=x,y=y,time=press)
                t.event_generate('<ButtonRelease-1>',x=x,y=y,time=press+10)
            settle(root,.8)
            assert seen==[value],(iid,seen,errors)
        detail(cid,M.CompanyDialog,'cid',d['cid'],5000)
        print('842: company detail ready',flush=True)
        assert t.item(cid,'open'),'Company body double-click must not collapse contacts'
        detail(pid,M.PersonDialog,'pid',d['pid'],10000)
        print('842: person detail ready',flush=True)
        assert w.editor.entry is None,'Person body double-click must open full detail'
        # Right-click changes selection to its actual row, even when another firm was selected.
        t.selection_set(f"c{d['other']}");x,y=coords(pid)
        # Windows native menu tracking is modal; inspect the real menu and its
        # commands without leaving an unattended OS menu open in the runner.
        with patch.object(M.tk.Menu,'tk_popup') as popup:
            t.event_generate('<Button-3>',x=x,y=y,rootx=t.winfo_rootx()+x,rooty=t.winfo_rooty()+y);settle(root)
            popup.assert_called_once()
        menu=w.row_menu
        print('842: context menu ready',flush=True)
        assert t.selection()==(pid,) and menu.entrycget(0,'label')=='Otevřít detail osoby'
        menu.invoke(3);settle(root)
        assert w.editor.column=='Telefon' and w.editor.entry is not None
        w.editor.variable.set('987654321');w.editor.entry.event_generate('<Return>');settle(root)
        assert sql(M,'SELECT phone FROM people WHERE id=?',(d['pid'],))[0][0]=='987654321'
        t.selection_set(pid);t.focus_force();t.event_generate('<F2>');settle(root)
        w.editor.variable.set('Anna Veselá upravená');w.editor.entry.event_generate('<Return>');settle(root)
        assert t.set(pid,'Společnost / kontakt').endswith('Anna Veselá upravená')
        assert sql(M,'SELECT name FROM people WHERE id=?',(d['pid'],))[0][0]=='Anna Veselá upravená'
        print('842: inline edit ready',flush=True)
        # Header events pass through to the existing table-column menu.
        assert w.context_menu(SimpleNamespace(x=50,y=4,keysym='')) is None
        # Read-only access keeps details available and disables inline mutations.
        row=access.profile(M,d['ids']['840 Alena'])
        access.save_profile(M,row['id'],'Technická podpora',{'people':1,'companies':1,'portfolio':1},(row['job_title'],row['tab_permissions']))
        root.active_user.set('840 Alena');root.refresh_user_access();root.show_page('portfolio');settle(root)
        w.query.set('842');w.refresh();t.item(cid,open=True);t.selection_set(pid);t.focus(pid);t.focus_force();settle(root)
        with patch.object(M.tk.Menu,'tk_popup'):
            t.event_generate('<Shift-F10>');settle(root)
        assert w.row_menu.entrycget(0,'state')=='normal'
        assert all(w.row_menu.entrycget(i,'state')=='disabled' for i in (2,3,4,5))
        w.row_menu.unpost()
        detail(pid,M.PersonDialog,'pid',d['pid'],15000)
        detail(cid,M.CompanyDialog,'cid',d['cid'],20000)
        assert not errors,errors
        print('8.0.42: native arrow/double-click details, hierarchy themes, correct context target, inline edits and read-only menus/details OK',flush=True)
    finally:
        root._turto_closing=True;root._mail_executor.shutdown(wait=False,cancel_futures=True)
        if root.map_workspace.bridge:root.map_workspace.bridge.close()
        for job in root.tk.splitlist(root.tk.call('after','info')):root.tk.call('after','cancel',job)
        root.destroy()


if __name__=='__main__':
    if '--ui-worker' in sys.argv:ui_checks(sys.argv[-1])
    else:
        with tempfile.TemporaryDirectory(prefix='turto-842-') as td:
            subprocess.run([sys.executable,'-B',__file__,*sys.argv[1:],'--ui-worker',td],check=True,timeout=150)
