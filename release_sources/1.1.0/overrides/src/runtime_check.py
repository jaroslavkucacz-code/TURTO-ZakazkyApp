"""Isolated release checks, executed only with explicit --turto-* self-test flags."""
import csv
import os
import tempfile
from pathlib import Path


def seed(root):
    from .db import Database
    from .data_import import preview_imports,apply_imports
    db=Database(root/'data/turto_dashboard.db')
    dl=[['Číslo','Datum','Kč základní','Firma','Středisko','Zakázka']]
    profits=[['Číslo DL','Datum','Firma','Kód','Název','Množství','Zisk celkem','Prodej celkem bez DPH','Náklad celkem bez DPH']]
    for year in (2025,2026):
        for i in range(1,31):
            no=f'{year%100}SV{i:05d}';dt=f'{year}-08-{(i-1)%28+1:02d}'
            value=1000*i if year==2025 else 1500*(31-i)
            company=f'Testovací zákazník {i:02d} – modelová stavební společnost'
            center=('M','J','H','')[i%4];project=f'Testovací zakázka {i%5}'
            dl.append([no,dt,value,company,center,project])
            if year==2026 and i<28:
                profits.append([no,dt,company,f'P{i%4}','Testovací výrobek',i,value*0.2,value,value*0.8])
    files=[]
    for name,rows in [('sample_delivery.csv',dl),('sample_profit.csv',profits)]:
        p=root/name
        with p.open('w',encoding='utf-8-sig',newline='') as f:csv.writer(f,delimiter=';').writerows(rows)
        files.append(p)
    batch=preview_imports(db,files);result=apply_imports(db,batch,root/'archives',root/'backups')
    assert result['changed']==87,result
    assert apply_imports(db,preview_imports(db,files),root/'archives',root/'backups')['changed']==0
    return db,files


def run_model_check():
    from .report_model import Analytics,collect_report
    from .exports import export_excel
    from .reporting import build_html
    with tempfile.TemporaryDirectory(prefix='turto_qa_') as temp:
        root=Path(temp);db,files=seed(root);a=Analytics(db)
        data=collect_report(a,2026,8)
        assert len(data['management']['customers'])==30
        assert len(data['management']['projects'])==5
        assert data['kpis']['count']==30
        assert data['kpis']['margin'] is None
        export_excel(root/'report.xlsx',a,2026,8)
        assert 'Kontrola měsíčních podkladů' in build_html(a,2026,8)
    return 0


def run_ui_check(screenshot=None,output=None):
    from .ui import App
    from .data_import import preview_imports
    from .exports import export_pdf,export_excel
    output=Path(output).resolve() if output else None
    if output:output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='turto_ui_qa_') as temp:
        root=Path(temp);db,files=seed(root)
        previous=os.environ.get('TURTO_REPORTING_DATA_ROOT');os.environ['TURTO_REPORTING_DATA_ROOT']=str(root)
        old=App._auto_check_updates;App._auto_check_updates=lambda self:None
        app=None
        try:
            app=App();app.geometry('1440x900');app.update();app.period_var.set('2026-08')
            errors=[];app.report_callback_exception=lambda *args:errors.append(str(args))
            pages=[('monthly',app.page_monthly_comparison),('customers',app.page_customer_changes),
                   ('projects',app.page_projects),('quality',app.page_data_quality),('imports',app.page_imports)]
            for name,method in pages:
                for child in app.container.winfo_children():child.destroy()
                method();app.update_idletasks();app.update()
                assert not errors,errors
                if screenshot and output:screenshot(app,output/(name+'.png'))
            app._preview_dialog(preview_imports(app.db,files));app.update()
            assert not errors,errors
            if screenshot and output:screenshot(app,output/'import-preview.png')
            # The modal can be cancelled without changing the seeded database.
            assert app.db.scalar('SELECT count(*) FROM delivery_notes')==60
            for child in app.winfo_children():
                import tkinter as tk
                if isinstance(child,tk.Toplevel):child.destroy()
            if output:
                export_excel(output/'sample-report.xlsx',app.analytics,2026,8)
                export_pdf(output/'sample-report.pdf',app.analytics,2026,8)
            app.destroy();app=None
        finally:
            if app is not None:app.destroy()
            App._auto_check_updates=old
            if previous is None:os.environ.pop('TURTO_REPORTING_DATA_ROOT',None)
            else:os.environ['TURTO_REPORTING_DATA_ROOT']=previous
    return 0
