#!/usr/bin/env python3
"""Received-offer controls, filter reset and separate MIVO profile presentation."""
from contextlib import closing
from datetime import date, timedelta
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

REPO=Path(__file__).resolve().parents[1]


def checks(td):
    spec=importlib.util.spec_from_file_location('mail_checks',REPO/'scripts/validate-829-request-mail.py')
    prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
    M=prior.previous.prepare(td,runtime=True);supplier=prior.seed(M)
    settle=prior.previous.settle
    from price_lists_domain.platform.calm_theme_820 import walk
    from price_lists_domain.platform import commercial_workspace as workspace
    M.set_setting('active_user','829 Alena')
    M.App.maybe_show_morning_overview=lambda self:None
    calls=[];errors=[]
    M.App.import_offer_sources=lambda self:calls.append('process')
    M.App.import_selected_outlook_offer=lambda self:calls.append('outlook')
    M.messagebox.showerror=lambda *a,**k:errors.append(a)
    M.messagebox.showwarning=lambda *a,**k:errors.append(a)
    M.messagebox.showinfo=lambda *a,**k:None
    with closing(M.db()) as con,con:
        pid=con.execute("INSERT INTO projects(name) VALUES('839 Ukázková akce')").lastrowid
        ids={}
        for name,days,archived,linked in [('recent',0,0,True),('old',60,0,False),('archive',0,1,True),('catalog',0,0,True)]:
            ids[name]=con.execute("""INSERT INTO supplier_offers(supplier_company_id,supplier_name,offer_number,
                offer_date,project_id,archived,source_hash,total_value,currency)
                VALUES(?,?,?,?,?,?,?,?,?)""",(supplier,'829 Dodavatel',name,(date.today()-timedelta(days=days)).isoformat(),
                pid if linked else None,archived,'839-'+name,15000,'CZK')).lastrowid
        con.execute("INSERT INTO price_lists(source_offer_id,title) VALUES(?, '839 Ceník')",(ids['catalog'],))
    root=M.App();root.report_callback_exception=lambda *args:errors.append(str(args))
    output=REPO/'build/validation/mail-offers-839';output.mkdir(parents=True,exist_ok=True)
    def shot(win,name):
        if '--no-screenshots' in sys.argv:return
        from PIL import ImageGrab
        settle(root,.3)
        ImageGrab.grab(bbox=(win.winfo_rootx(),win.winfo_rooty(),
                            win.winfo_rootx()+win.winfo_width(),win.winfo_rooty()+win.winfo_height())).save(output/name)
    def button(text):
        return next(w for w in walk(root.tabs['offers']) if w.winfo_class()=='TButton' and w.winfo_viewable() and str(w.cget('text')).endswith(text))
    def rows():
        return {int(i[1:]) for i in root.offer_tree.get_children()}
    try:
        root.apply_theme('Světlý');root.show_page('offers');settle(root,2)
        load=button('Načíst z Outlooku');process=button('Zpracovat nabídku')
        assert load.master is process.master
        assert abs(load.winfo_rooty()-process.winfo_rooty())<3
        left,right=sorted((load,process),key=lambda w:w.winfo_rootx())
        assert 0<=right.winfo_rootx()-left.winfo_rootx()-left.winfo_width()<=16
        process.invoke();load.invoke();settle(root)
        assert calls==['process','outlook'],calls
        texts=[str(w.cget('text')) for w in walk(root.tabs['offers']) if 'text' in w.keys()]
        assert not any(text.startswith('Barvy jsou upozornění') for text in texts)
        views=button('Nepřiřazeno k akci').master
        labels=[str(w.cget('text')) for w in views.winfo_children() if w.winfo_class()=='TButton']
        assert labels==['Posledních 30 dní','Nepřiřazeno k akci','Ceníky','Archivované'],labels
        assert rows()=={ids['recent'],ids['old'],ids['catalog']},rows()
        for label,expected in [('Posledních 30 dní',{'recent','catalog'}),('Nepřiřazeno k akci',{'old'}),
                               ('Ceníky',{'catalog'}),('Archivované',{'archive'})]:
            button(label).invoke();settle(root)
            assert rows()=={ids[k] for k in expected},(label,rows())
            button('Zrušit filtrování').invoke();settle(root)
            assert rows()=={ids['recent'],ids['old'],ids['catalog']}
        assert root.offer_tree._turto_configurable_columns
        shot(root,'received-offers-light.png')
        root.apply_theme('Tmavý');settle(root)
        shot(root,'received-offers-dark.png')
        root.apply_theme('Světlý')
        dialog=M.RequestDialog(root,pre_company='MIVO 839');settle(root)
        assert dialog.subject.get().startswith('TURTO - MIVO 839')
        assert dialog.mail_profile_button.cget('text')=='Výchozí text MIVO…'
        assert dialog.mail_body.get('1.0','end-1c')=='Samostatný text MIVO\nAlena'
        dialog._dialog_canvas.yview_moveto(.55);settle(root)
        shot(dialog,'mivo-mail.png')
        dialog.destroy()
        assert not errors,errors
        print('8.0.39: Outlook/process commands adjacent, four work views/reset, no legend, MIVO template UI OK',flush=True)
    finally:
        for w in root.winfo_children():
            if isinstance(w,M.tk.Toplevel):w.destroy()
        if root.map_workspace.bridge:root.map_workspace.bridge.close()
        root._turto_closing=True
        for job in root.tk.splitlist(root.tk.call('after','info')):root.tk.call('after','cancel',job)
        root.destroy()


if __name__=='__main__':
    if '--worker' in sys.argv:checks(sys.argv[-1])
    else:
        with tempfile.TemporaryDirectory(prefix='turto-mail-offers-839-') as td:
            subprocess.run([sys.executable,__file__,*sys.argv[1:],'--worker',td],check=True,timeout=120)
