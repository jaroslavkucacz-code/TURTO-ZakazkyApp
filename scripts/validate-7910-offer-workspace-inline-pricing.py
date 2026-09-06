#!/usr/bin/env python3
"""Validate compact issued-offer workspace and inline internal profitability."""
from __future__ import annotations
from contextlib import nullcontext
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback


def main():
    source=Path(sys.argv[1] if len(sys.argv)>1 else 'ZakazkyApp_base_6.1').resolve()
    if '--worker' not in sys.argv:
        with tempfile.TemporaryDirectory(prefix='turto_791_ui_') as tmp:
            subprocess.run([sys.executable,str(Path(__file__).resolve()),str(source),'--worker',tmp],check=True,timeout=120)
        return
    workspace=sys.argv[sys.argv.index('--worker')+1]
    with nullcontext(workspace) as tmp:
        os.environ.update(HOME=tmp,USERPROFILE=tmp,TURTO_DISABLE_AUTO_UPDATE='1')
        sys.path.insert(0,str(source));os.chdir(source)
        import importlib.util
        baseline_path=source.parent/'post_baseline.py'
        spec=importlib.util.spec_from_file_location('post_baseline',baseline_path)
        baseline=importlib.util.module_from_spec(spec);sys.modules['post_baseline']=baseline;spec.loader.exec_module(baseline)
        import app as M, runtime_bootstrap
        from price_lists_domain.issued_offers import service, editor, inline_pricing_workspace as work
        M.ensure_schema();runtime_bootstrap.apply_all(M);M.ensure_schema();M.ensure_test_user()
        assert 'price_lists_domain.issued_offers.inline_pricing_workspace' in runtime_bootstrap.LATE_LAYERS
        M.App.maybe_show_morning_overview=lambda self:None
        original_state=M.App.state
        if not sys.platform.startswith('win'):
            M.App.state=lambda self,newstate=None:original_state(self) if newstate in (None,'zoomed') else original_state(self,newstate)
        errors=[]
        M.messagebox.showwarning=lambda *a,**kw:errors.append(str(a))
        M.messagebox.showerror=lambda *a,**kw:errors.append(str(a))
        M.messagebox.showinfo=lambda *a,**kw:None
        root=M.App();root.report_callback_exception=lambda *e:errors.append(''.join(traceback.format_exception(*e)))
        root.geometry('1500x900')
        def pump(seconds=.25):
            end=time.monotonic()+seconds
            while time.monotonic()<end:
                root.update();time.sleep(.01)
        try:
            pump(.8)
            document=service.offer_defaults(M)
            document.update(customer_name_snapshot='Test s.r.o.',offer_subject='Inline marže',global_discount_pct=10)
            items=[
                {'row_type':'heading','name':'Sekce A'},
                {'row_type':'product','name':'Položka A','quantity':10,'unit':'ks','purchase_unit_price':100,'margin_pct':50,'discount_pct':10,'recommended_unit_price':150,'unit_price':135,'vat_rate':21},
                {'row_type':'product','name':'Položka B','quantity':5,'unit':'m','purchase_unit_price':200,'margin_pct':25,'discount_pct':0,'recommended_unit_price':250,'unit_price':250,'vat_rate':12},
            ]
            view=editor.IssuedOfferEditor(M,root,initial_document=document,initial_items=items)
            pump(.8)
            panel=view._v791_pricing_panel
            assert panel.frame.winfo_ismapped(), 'pricing panel must be default visible'
            assert not view._v791_metadata_panel.winfo_ismapped(), 'metadata must default collapsed'
            assert len(panel.tree.get_children(''))==len(items)
            assert 'DPH' not in panel.summary.get()
            assert 'Zisk' in panel.summary.get()
            assert round(work._profit(service,items[1],10),2)==215.00
            assert round(work._profit(service,items[2],10),2)==125.00
            purchase,sale,profit=work._profit_totals(service,items,10)
            assert (round(purchase,2),round(sale,2),round(profit,2))==(2000.00,2340.00,340.00)
            assert '340,00' in panel.summary.get(),panel.summary.get()
            panel._open_editor('p1','#3');pump(.1)
            assert panel.edit_widget is not None
            panel.edit_variable.set('60')
            panel.commit_edit();pump(.35)
            updated=service.normalize_item(view.items[1])
            assert round(updated['margin_pct'],2)==60.0
            assert round(updated['recommended_unit_price'],2)==160.0
            assert round(updated['unit_price'],2)==144.0
            assert 'DPH' not in view.totals_text.get()
            assert 'Zisk' in view.totals_text.get()
            view._v791_metadata_button.invoke();pump(.1)
            assert view._v791_metadata_panel.winfo_ismapped()
            view._v791_metadata_button.invoke();pump(.1)
            assert not view._v791_metadata_panel.winfo_ismapped()
            assert getattr(view,'_v720_preview',None) is not None
            view.win.destroy();pump(.1)
            assert not errors,'\n'.join(errors)
        finally:
            root.destroy()
    print('OK 7.9.1: compact offer workspace, all-row inline margin/discount/purchase edit and profit without DPH')

if __name__=='__main__':main()
