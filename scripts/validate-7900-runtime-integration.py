#!/usr/bin/env python3
"""Exercise the new template in the complete, real Tk runtime composition."""
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
        # A normal CRM exit ends the Python process and releases its SQLite/OLE
        # handles. Do not delete its working database while that process exists.
        # Run all real UI assertions unchanged, without monkeypatching M.db.
        with tempfile.TemporaryDirectory(prefix='turto_790_full_') as tmp:
            try:
                subprocess.run([sys.executable,str(Path(__file__).resolve()),str(source),'--worker',tmp],check=True,timeout=120)
            except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
                for log in Path(tmp).rglob('*crash*.log'):
                    print(log.read_text(encoding='utf-8',errors='replace')[-12000:],file=sys.stderr)
                raise
        return
    workspace=sys.argv[sys.argv.index('--worker')+1]
    with nullcontext(workspace) as tmp:
        os.environ.update(HOME=tmp,USERPROFILE=tmp,TURTO_DISABLE_AUTO_UPDATE='1')
        sys.path.insert(0,str(source));os.chdir(source)
        # publish-update.sh explicitly copies this one root module into the
        # release; do not prioritize the entire repository over current source.
        import importlib.util
        baseline_path = source.parent / 'post_baseline.py'
        spec = importlib.util.spec_from_file_location('post_baseline', baseline_path)
        baseline = importlib.util.module_from_spec(spec)
        sys.modules['post_baseline'] = baseline
        spec.loader.exec_module(baseline)
        import app as M
        import runtime_bootstrap
        import inspect
        import v770_runtime_policy
        assert 'update_idletasks(' not in inspect.getsource(v770_runtime_policy._place_dialog)
        from price_lists_domain.issued_offers import service,template_layout,template_settings,editor
        M.ensure_schema();runtime_bootstrap.apply_all(M);M.ensure_schema();M.ensure_test_user()
        # The installer copies modules from source; only post_baseline comes
        # from repository root. Historical root duplicates must not be loaded.
        assert Path(M.__file__).resolve().parent == source
        layer_names = (*runtime_bootstrap.EARLY_LAYERS, *runtime_bootstrap.LATE_LAYERS,
                       'runtime_bootstrap', 'v644_default_date_sort', 'v631_diskdrop', 'crm_price_lists')
        for name in layer_names:
            assert Path(sys.modules[name].__file__).resolve().is_relative_to(source), name
        assert Path(sys.modules['post_baseline'].__file__).resolve() == baseline_path
        M.App.maybe_show_morning_overview=lambda self:None
        original_state=M.App.state
        if not sys.platform.startswith('win'):
            M.App.state=lambda self,newstate=None:original_state(self) if newstate in (None,'zoomed') else original_state(self,newstate)
        errors=[]
        for name in ('showwarning','showerror'):
            setattr(M.messagebox,name,lambda *a,**kw:errors.append(str(a)))
        M.messagebox.showinfo=lambda *a,**kw:None
        root=M.App();root.report_callback_exception=lambda *e:errors.append(''.join(traceback.format_exception(*e)))
        root.geometry('1480x920')
        def pump(seconds=.3):
            end=time.monotonic()+seconds
            while time.monotonic()<end:root.update();time.sleep(.01)
        try:
            pump(1.5)
            assert M._turto_runtime_bootstrap_complete
            root.show_page('issued_offers');pump()
            default=service.load_template(M);assert template_layout.is_corporate(default)
            values=dict(default);values.pop('builtin_key');values['name']='Integrační vlastní';values['is_default']=0
            tid=service.save_template(M,values)
            doc,items=template_settings.sample_offer();doc.update(template_id=tid, document_number="INTEGRAČNÍ NÁHLED", customer_note="Skutečný neuložený obsah nabídky")
            for item in items:item['internal_name_snapshot']=item['name']
            view=editor.IssuedOfferEditor(M,root,initial_document=doc,initial_items=items)
            pump(.8)
            preview=view._v720_preview
            preview.visible=True;preview.refresh();pump()
            assert preview.images,preview.status.get()
            assert len(preview.canvas_regions)==len(items),preview.status.get()
            assert sorted({r['index'] for r in preview.canvas_regions})==list(range(len(items)))
            assert view.template_settings_button.winfo_exists()
            def visit_child():
                for child in view.win.winfo_children():
                    controller=getattr(child,'_turto_template_editor',None)
                    if controller is not None:
                        assert controller.preview_document["document_number"] == "INTEGRAČNÍ NÁHLED"
                        assert controller.preview_document["customer_note"] == "Skutečný neuložený obsah nabídky"
                        assert len(controller.preview_items) == len(items)
                        if os.environ.get('TURTO_TEMPLATE_SCREENSHOT'):
                            from PIL import ImageGrab
                            controller.render_preview();root.update_idletasks()
                            w=controller.win
                            box=(w.winfo_rootx(),w.winfo_rooty(),w.winfo_rootx()+w.winfo_width(),w.winfo_rooty()+w.winfo_height())
                            ImageGrab.grab(box).save(os.environ['TURTO_TEMPLATE_SCREENSHOT'])
                        controller.layout_vars['font_size'].set('10')
                        controller.save();controller.close();return
                view.win.after(100,visit_child)
            view.win.after(500,visit_child)
            view.edit_pdf_template();pump()
            assert template_layout.normalize(service.load_template(M,tid)['layout_json'])['font_size']==10
            assert view.win.grab_current()==view.win
            assert view.template_map[view.template.get()]==tid
            preview.refresh();pump()
            assert preview.images and preview.canvas_regions
            view.win.destroy();pump()
            assert not errors,'\n'.join(errors)
        finally:
            root.destroy()
    print('OK 7.9 full bootstrap: real issued editor, same-renderer hit regions, modal template child, persisted edits and refreshed preview')

if __name__=='__main__':main()
