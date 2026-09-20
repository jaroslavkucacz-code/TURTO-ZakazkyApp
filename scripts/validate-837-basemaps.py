#!/usr/bin/env python3
"""Real Windows basemap switching, live imagery and unchanged CRM locations."""
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

REPO=Path(__file__).resolve().parents[1]


def ui_checks(td):
    spec=importlib.util.spec_from_file_location('prior',REPO/'scripts/validate-835-map.py')
    prior=importlib.util.module_from_spec(spec); spec.loader.exec_module(prior)
    M,settle=prior.prepare(td); ids=prior.seed(M)
    from price_lists_domain.maps import model
    M.set_setting('active_user','835 Editor'); M.App.maybe_show_morning_overview=lambda self:None
    errors=[]; warnings=[]
    M.messagebox.showwarning=lambda *a,**k:warnings.append(a)
    M.messagebox.showerror=lambda *a,**k:errors.append(a)
    M.messagebox.showinfo=lambda *a,**k:None
    M.messagebox.askyesno=lambda *a,**k:True
    root=M.App(); root.geometry('1420x980+0+0')
    root.report_callback_exception=lambda kind,value,tb:errors.append(str(value))
    def wait(predicate,description,timeout=75):
        end=time.monotonic()+timeout
        while not predicate() and time.monotonic()<end: settle(root,.1)
        assert predicate(), f'{description}: {root.map_workspace.status.get()}; {errors}'
    output=REPO/'build/validation/basemaps-837'; output.mkdir(parents=True,exist_ok=True)
    def screenshot(name):
        from PIL import ImageGrab
        settle(root,1)
        ImageGrab.grab(bbox=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height())).save(output/name)
    try:
        root.select_user('835 Editor'); root.show_page('map'); w=root.map_workspace
        wait(lambda:w.loaded and w.basemap_ready=='map','Original map did not load')
        assert not hasattr(w,'company_box') and not hasattr(w,'company_ids')
        assert w.layer.get()=='Akce'
        assert set(w.records)=={r['key'] for r in model.rows(M,layer='project')}
        w.layer.set('Vybráno vše');w.layer_box.event_generate('<<ComboboxSelected>>');settle(root,.3)
        assert set(w.records)=={r['key'] for r in model.rows(M)}
        w.layer.set('Akce');w.layer_box.event_generate('<<ComboboxSelected>>');settle(root,.3)
        w.tree.selection_set(f"project:{ids['project']}"); settle(root,.2)
        before=model.record(M,'project',ids['project'])
        point=[14.42,50.08]
        w.show_matches([{'gps':'50.08, 14.42','coordinates':point,'label':'Náhled stavby',
                         'source':'ruian-parcel','code':'123'}],dict(w.selected()))
        wait(lambda:w.last_preview_point==point,'Preview missing')
        settle(root,3)
        w.pick(); settle(root,.2)
        w.basemap_button.menu.invoke(0); settle(root,.4)
        baseline=w.last_basemap_state
        assert baseline['picking'] and baseline['preview']==point
        selection=w.tree.selection()
        w.basemap_button.menu.invoke(1)
        wait(lambda:w.basemap_ready=='orthophoto','Live CUZK imagery did not load')
        state=w.last_basemap_state
        assert state['value']=='orthophoto'
        for field in ('center','zoom','count','preview','picking'):
            assert state[field]==baseline[field], (field,state,baseline)
        assert w.tree.selection()==selection and w.pending_pick
        assert model.snapshot(model.record(M,'project',ids['project']))==model.snapshot(before)
        screenshot('orthophoto.png')
        w.basemap_button.menu.invoke(0)
        wait(lambda:w.basemap_ready=='map','Return to normal map failed')
        assert w.last_basemap_state['center']==baseline['center']
        assert w.last_basemap_state['preview']==point and w.pending_pick
        screenshot('standard-map.png')
        w.basemap_button.menu.invoke(1)
        wait(lambda:w.basemap_ready=='orthophoto','Second switch failed')
        w.cancel_pick(); w.reload()
        wait(lambda:w.loaded and w.basemap_ready=='orthophoto','Reload forgot selected background')
        wait(lambda:w.last_preview_point==point,'Reload lost parcel preview')
        assert model.snapshot(model.record(M,'project',ids['project']))==model.snapshot(before)
        assert not errors and not warnings,(errors,warnings)
        (output/'basemaps-report.json').write_text(json.dumps({'ok':True,
            'live_cuzk_imagery':True,'preserved_camera_selection_preview_pick':True,
            'company_filter_removed':True,'reload_preserved_background':True},indent=2),encoding='utf-8')
        print('8.0.37: real WebView2 orthophoto, one-click switches, unchanged GPS/selection/camera/preview and reload OK',flush=True)
    finally:
        w=root.map_workspace;w.cancel_job(quiet=True)
        if w.bridge:w.bridge.close()
        root._turto_closing=True
        for job in root.tk.splitlist(root.tk.call('after','info')):root.tk.call('after','cancel',job)
        root.destroy()


if __name__=='__main__':
    if '--ui-worker' in sys.argv:
        ui_checks(sys.argv[-1]);raise SystemExit(0)
    subprocess.run(['node',str(REPO/'scripts/validate-837-map-renderer.js')],check=True)
    if '--source-only' not in sys.argv:
        with tempfile.TemporaryDirectory(prefix='turto-basemaps-') as td:
            subprocess.run([sys.executable,__file__,'--ui-worker',td],check=True,timeout=240)
