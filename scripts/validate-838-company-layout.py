#!/usr/bin/env python3
"""Folded company fields must retain edits, ARES values and read-only access."""
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

REPO=Path(__file__).resolve().parents[1]
DETAILS={'legal_form':'112','date_created':'2000-11-28','ares_last_change':'2026-09-01',
         'cz_nace':'68200, 181','financial_office':'027','municipality':'Osek'}


def checks(td):
    spec=importlib.util.spec_from_file_location('prior',REPO/'scripts/validate-835-map.py')
    prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
    M,settle=prior.prepare(td);ids=prior.seed(M)
    from price_lists_domain.platform.form_behavior_817 import children,editable
    M.set_setting('active_user','835 Editor');M.App.maybe_show_morning_overview=lambda self:None
    errors=[];warnings=[]
    M.messagebox.showerror=lambda *a,**k:errors.append(a)
    M.messagebox.showwarning=lambda *a,**k:warnings.append(a)
    M.messagebox.showinfo=lambda *a,**k:None
    M.messagebox.askyesno=lambda *a,**k:True
    M.messagebox.askyesnocancel=lambda *a,**k:False
    with closing(M.db()) as con,con:
        for key,value in DETAILS.items():
            con.execute(f'UPDATE companies SET {key}=? WHERE id=?',(value,ids['cid']))
        con.execute("UPDATE companies SET district='Beroun' WHERE id=?",(ids['cid'],))
        con.execute("UPDATE users SET tab_permissions=? WHERE name='835 Reader'",
                    (json.dumps({'companies':1,'map':1,'projects':1}),))
    root=M.App();root.geometry('1420x980+0+0')
    root.report_callback_exception=lambda kind,value,tb:errors.append(str(value))
    output=REPO/'build/validation/layout-838';output.mkdir(parents=True,exist_ok=True)
    def shot(win,name):
        if '--no-screenshots' in sys.argv:return
        from PIL import ImageGrab
        settle(root,.3)
        ImageGrab.grab(bbox=(win.winfo_rootx(),win.winfo_rooty(),win.winfo_rootx()+win.winfo_width(),win.winfo_rooty()+win.winfo_height())).save(output/name)
    def entry(dialog,key):
        return next(w for w in children(dialog) if w.winfo_class()=='TEntry' and str(w.cget('textvariable'))==str(dialog.vars[key]))
    def saved():
        with closing(M.db()) as con:return dict(con.execute('SELECT * FROM companies WHERE id=?',(ids['cid'],)).fetchone())
    try:
        root.select_user('835 Editor');root.show_page('companies');settle(root,.3)
        dialog=M.CompanyDialog(root,ids['cid']);settle(root,.5)
        assert not dialog.extra_company_details.winfo_ismapped()
        assert all(not editable(entry(dialog,key)) for key in DETAILS)
        assert editable(entry(dialog,'district')) and editable(entry(dialog,'gps_coordinates'))
        assert not dialog._turto_form_guard.changed()
        shot(dialog,'company-collapsed.png')
        dialog.extra_details_button.invoke();settle(root,.2)
        assert all(editable(entry(dialog,key)) for key in DETAILS)
        assert not dialog._turto_form_guard.changed(), 'Expanding the section dirtied the form'
        canvas=getattr(dialog,'_dialog_canvas',None)
        if canvas:canvas.yview_moveto(.3)
        shot(dialog,'company-expanded.png')
        dialog.extra_details_button.invoke();settle(root,.2)
        assert not dialog._turto_form_guard.changed()
        dialog.vars['web'].set('https://example.org')
        dialog.ok();settle(root,.2)
        assert not dialog.winfo_exists()
        assert all(saved()[key]==value for key,value in DETAILS.items()),'Saving a collapsed form lost data'

        dialog=M.CompanyDialog(root,ids['cid']);settle(root,.3)
        updated={key:value+' test' for key,value in DETAILS.items()}
        dialog.ares_results=[dict(updated,official_name='838 Firma z ARES',district='Praha')]
        dialog.results.insert('end','838 Firma z ARES');dialog.results.selection_set(0)
        dialog.take_ares()
        assert not dialog.extra_company_details.winfo_ismapped()
        assert dialog._turto_form_guard.changed(),'Hidden ARES changes were not tracked'
        dialog.extra_details_button.invoke();settle(root,.2)
        assert all(entry(dialog,key).get()==value for key,value in updated.items())
        entry(dialog,'legal_form').delete(0,'end');entry(dialog,'legal_form').insert(0,'121')
        updated['legal_form']='121'
        dialog.extra_details_button.invoke();dialog.ok();settle(root,.2)
        assert not dialog.winfo_exists()
        assert all(saved()[key]==value for key,value in updated.items())

        root.select_user('835 Reader');settle(root,.3)
        dialog=M.CompanyDialog(root,ids['cid']);settle(root,.3)
        assert not dialog.extra_details_button.instate(['disabled'])
        dialog.extra_details_button.invoke();settle(root,.2)
        assert dialog.extra_company_details.winfo_ismapped()
        assert all(entry(dialog,key).instate(['disabled']) for key in DETAILS)
        assert not dialog._turto_form_guard.changed()
        dialog.destroy()
        menu=root.map_workspace.basemap_button
        assert not menu.instate(['disabled']),'Read-only user cannot change map background'
        menu.menu.invoke(1);assert root.map_workspace.basemap.get()=='orthophoto'
        assert not errors and not warnings,(errors,warnings)
        print('8.0.38: collapsed company/ARES values saved, expansion stays clean, readers can inspect without editing',flush=True)
    finally:
        for child in root.winfo_children():
            if isinstance(child,M.tk.Toplevel):child.destroy()
        if root.map_workspace.bridge:root.map_workspace.bridge.close()
        root._turto_closing=True
        for job in root.tk.splitlist(root.tk.call('after','info')):root.tk.call('after','cancel',job)
        root.destroy()


if __name__=='__main__':
    if '--worker' in sys.argv:checks(sys.argv[-1])
    else:
        with tempfile.TemporaryDirectory(prefix='turto-layout-838-') as td:
            subprocess.run([sys.executable,__file__,*sys.argv[1:],'--worker',td],check=True,timeout=120)
