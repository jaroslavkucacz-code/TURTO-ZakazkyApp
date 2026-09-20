#!/usr/bin/env python3
"""Online lookup identities, ambiguity, cancellation, CAS and real Tk flows."""
from contextlib import closing
import copy
import importlib.util
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'ZakazkyApp_base_6.1'))
from price_lists_domain.maps import model, online, workspace
from price_lists_domain.platform import user_access as access

ADDRESS = 'Pod sídlištěm 1800/9, 18200 Praha 8'
LABEL = 'Pod sídlištěm 1800/9, Kobylisy, 18200 Praha 8'
KU = {'name':'Kobylisy','code':730475,'label':'Kobylisy [730475]'}
MATCH = {'label':LABEL,'code':'25133616','gps':'50.1250120, 14.4555578',
         'coordinates':[14.4555578,50.1250120],'source':'ruian'}
PARCEL = dict(MATCH,label='Parcela 1/2, k. ú. Kobylisy [730475]',code='2234342101',source='ruian-parcel')


class LookupTests(unittest.TestCase):
    def test_service_object_ids_are_resolved_to_current_ruian_codes(self):
        client=online.Client()
        def request(path,**params):
            if path.endswith('/suggest'):
                self.assertEqual(params['text'],ADDRESS)
                return {'suggestions':[{'magicKey':'1153291','text':LABEL,'isCollection':False}]}
            self.assertEqual(params['objectIds'],'1153291')
            self.assertEqual(params['outSR'],4326)
            return {'features':[{'attributes':{'kod':25133616,'adresa':LABEL,'platido':None,'nespravny':None},
                                 'geometry':{'x':14.4555578,'y':50.1250120}}]}
        with patch.object(client,'request',side_effect=request):
            self.assertEqual(client.addresses(ADDRESS),[MATCH])

    def test_batch_requires_full_unique_address_without_number_substitution(self):
        self.assertEqual(online.exact_address(ADDRESS,[MATCH]),MATCH)
        self.assertEqual(online.exact_address('Pod sidlistem 1800/9, Praha 8, 182 00, Česká republika',[MATCH]),MATCH)
        for address in ('Pod sídlištěm 1800, 18200 Praha 8','Pod sídlištěm 9/1800, 18200 Praha 8',
                        'Pod sídlištěm 1801/9, 18200 Praha 8','Pod sídlištěm 1800/9, Praha 8',
                        'Pod sídlištěm č.ev. 1800/9, 18200 Praha 8','Pod sídlištěm 1800/9, 18200 Praha 9'):
            self.assertIsNone(online.exact_address(address,[MATCH]),address)
        self.assertIsNone(online.exact_address(ADDRESS,[MATCH,dict(MATCH,code='2')]))

    def test_bounded_results_invalid_coordinates_and_expired_records(self):
        client=online.Client()
        for response in ({'suggestions':[{'magicKey':'1','isCollection':True}]},
                         {'suggestions':[{'magicKey':str(n+1)} for n in range(21)]},
                         {'suggestions':[{'magicKey':'1 OR 1=1'}]},{}):
            with patch.object(client,'request',return_value=response), self.assertRaises(ValueError):
                client.addresses(ADDRESS)
        for longitude in (float('nan'),742000,200):
            with self.assertRaises(ValueError): online._point({'geometry':{'x':longitude,'y':50}})
        with patch.object(client,'_suggest',return_value='1'), patch.object(client,'_features',return_value=[
            {'attributes':{'kod':1,'adresa':LABEL,'platido':100,'nespravny':None},'geometry':{'x':14,'y':50}}]):
            self.assertEqual(client.addresses(ADDRESS),[])

    def test_cadastre_name_and_code(self):
        client=online.Client()
        features=[{'attributes':{'kod':730475,'nazev':'Kobylisy','platido':None,'nespravny':None}}]
        with patch.object(client,'_features',return_value=features) as query:
            self.assertEqual(client.cadastres('730475'),[KU])
            self.assertEqual(query.call_args.kwargs['where'],'kod=730475')
        with patch.object(client,'_suggest',return_value='5339') as suggest, patch.object(client,'_features',return_value=features) as query:
            self.assertEqual(client.cadastres('Kobylisy'),[KU])
            suggest.assert_called_once_with(7,'Kobylisy')
            self.assertEqual(query.call_args.kwargs['objectIds'],'5339')

    def test_parcel_full_identity_and_building_land_ambiguity(self):
        client=online.Client()
        feature={'attributes':{'id':2234342101,'katastralniuzemi':730475,'kmenovecislo':1,
                  'poddelenicisla':2,'druhcislovanikod':2,'platido':None,'nespravny':None},
                 'geometry':{'x':14.4555578,'y':50.1250120}}
        building=copy.deepcopy(feature); building['attributes'].update(id=2234342102,druhcislovanikod=1)
        with patch.object(client,'_features',return_value=[feature,building]) as query:
            result=client.parcels(KU,'1/2')
            self.assertEqual(len(result),2)
            self.assertNotEqual(result[0]['label'],result[1]['label'])
            self.assertIn('katastralniuzemi=730475',query.call_args.kwargs['where'])
            self.assertIn('poddelenicisla=2',query.call_args.kwargs['where'])
        with patch.object(client,'_features',return_value=[building]) as query:
            self.assertIn('st. 1/2',client.parcels(KU,'st. 1/2')[0]['label'])
            self.assertIn('druhcislovanikod=1',query.call_args.kwargs['where'])
        wrong=copy.deepcopy(feature); wrong['attributes']['katastralniuzemi']=999999
        with patch.object(client,'_features',return_value=[wrong]), self.assertRaises(online.ServiceError):
            client.parcels(KU,'1/2')
        with patch.object(client,'_features',return_value=[]):
            self.assertEqual(client.parcels(KU,'99999/99999'),[])
        for bad in ('0','1/0','1/2/3','1 OR 1=1','-1','12a','123456'):
            with self.assertRaises(ValueError): online.parse_parcel(bad)
        with self.assertRaises(ValueError): online.parse_parcel('st. 1','land')

    def test_batch_deduplicates_reports_partial_failure_and_cancels(self):
        client=online.Client()
        records=[{'id':n,'address':address} for n,address in enumerate((ADDRESS,ADDRESS,'Jiná 1, 10000 Praha'))]
        with patch.object(client,'addresses',side_effect=[[MATCH],online.ServiceError('Offline')]) as calls:
            result=online.batch_addresses(records,client)
            self.assertEqual(calls.call_count,2)
            self.assertEqual(len(result['matches']),2)
            self.assertEqual(result['unprocessed'],1)
            self.assertEqual(result['error'],'Offline')
        client.cancel.set()
        with patch.object(client.opener,'open') as network, self.assertRaises(online.Cancelled):
            client.addresses(ADDRESS)
        network.assert_not_called()

    def test_http_errors_and_host_restriction(self):
        client=online.Client()
        with patch.object(client.opener,'open',side_effect=TimeoutError), self.assertRaises(online.ServiceError):
            client.addresses(ADDRESS)
        with self.assertRaises(ValueError): client.request('https://example.org/')
        with self.assertRaises(online.ServiceError):
            online._SafeRedirect().redirect_request(None,None,302,'',{},'https://evil.test/')

    def test_location_provenance_cas_and_manual_override(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'crm.sqlite'
            def db():
                con=sqlite3.connect(path); con.row_factory=sqlite3.Row; return con
            M=SimpleNamespace(db=db,normalize_gps=lambda value:value)
            with closing(db()) as con,con:
                for table in ('companies','projects'):
                    con.execute(f"CREATE TABLE {table}(id INTEGER PRIMARY KEY,address TEXT DEFAULT '',active INTEGER DEFAULT 1)")
                model.ensure_schema(con); model.ensure_schema(con)
                con.execute('INSERT INTO projects(id) VALUES(1)')
            row=model.record(M,'project',1); original=model.snapshot(row)
            model.save_location(M,'project',1,PARCEL['gps'],original,PARCEL['source'],PARCEL['code'],PARCEL['label'])
            saved=model.record(M,'project',1)
            self.assertEqual(saved['map_label'],PARCEL['label'])
            self.assertEqual(saved['address'],'')
            self.assertEqual(saved['map_source'],'ruian-parcel')
            with self.assertRaises(ValueError): model.save_location(M,'project',1,MATCH['gps'],original)
            with patch.object(access,'level',return_value=access.READ),self.assertRaises(access.AccessDenied):
                model.save_location(M,'project',1,MATCH['gps'],model.snapshot(saved))
            model.save_location(M,'project',1,'50.1,14.4',model.snapshot(saved))
            manual=model.record(M,'project',1)
            self.assertEqual((manual['map_label'],manual['map_ruian_id'],manual['map_source']),('','','manual'))

    def test_old_worker_cannot_end_new_job(self):
        w=workspace.Workspace.__new__(workspace.Workspace)
        w.jobs=queue.Queue(); w.jobs.put(('error',1,'old user'))
        w.generation=2; w.job_running=True
        w.page=SimpleNamespace(after=lambda *args:'scheduled')
        w.poll()
        self.assertTrue(w.job_running)


def ui_checks(td):
    spec=importlib.util.spec_from_file_location('map835',REPO/'scripts/validate-835-map.py')
    prior=importlib.util.module_from_spec(spec); spec.loader.exec_module(prior)
    M,settle=prior.prepare(td); ids=prior.seed(M)
    M.set_setting('active_user','835 Editor'); M.App.maybe_show_morning_overview=lambda self:None
    warnings=[]; errors=[]; confirmations=[]
    M.messagebox.showwarning=lambda *a,**k:warnings.append(a)
    M.messagebox.showerror=lambda *a,**k:errors.append(a)
    M.messagebox.showinfo=lambda *a,**k:None
    M.messagebox.askyesno=lambda *a,**k:(confirmations.append(a) or True)
    root=M.App(); root.geometry('1420x980+0+0')
    root.report_callback_exception=lambda kind,value,tb:errors.append(str(value))
    def wait_job(w):
        deadline=time.monotonic()+10
        while w.job_running and time.monotonic()<deadline: settle(root,.05)
        assert not w.job_running, 'Online worker did not finish'
        settle(root,.15)
    try:
        root.select_user('835 Editor'); root.show_page('map'); settle(root,.3)
        w=root.map_workspace
        with closing(M.db()) as con,con:
            for cid in (ids['cid'],ids['cid2']):
                con.execute("UPDATE companies SET address=?,gps_coordinates='',map_source='',map_label='' WHERE id=?",(ADDRESS,cid))
        w.refresh(); w.tree.selection_set([f"company:{ids['cid']}",f"company:{ids['cid2']}"]); settle(root)
        assert w.selected() is None
        with patch.object(online.Client,'addresses',return_value=[MATCH]):
            w.batch_lookup(); wait_job(w)
        assert all(model.record(M,'company',ids[k])['gps_coordinates']==MATCH['gps'] for k in ('cid','cid2'))
        assert len(confirmations)==1
        w.tree.selection_set(f"project:{ids['target']}"); settle(root)
        w.cadastre_query.set('Kobylisy')
        with patch.object(online.Client,'cadastres',return_value=[KU]):
            w.find_cadastres(); wait_job(w)
        assert w.cadastre_choice.get()==KU['label']
        w.parcel_number.set('1/2')
        with patch.object(online.Client,'parcels',return_value=[PARCEL]):
            w.find_parcel(); wait_job(w)
        assert w.preview['source']=='ruian-parcel'
        assert not model.record(M,'project',ids['target'])['gps_coordinates'], 'Preview wrote CRM data'
        button,canvas=w.save_found_button,w.details_canvas
        assert button.winfo_rooty() >= canvas.winfo_rooty(), 'Save button hidden above viewport'
        assert button.winfo_rooty()+button.winfo_height() <= canvas.winfo_rooty()+canvas.winfo_height(), 'Save button hidden below viewport'
        deadline=time.monotonic()+60
        while w.last_preview_point != PARCEL['coordinates'] and time.monotonic()<deadline:
            settle(root,.1)
        output=REPO/'build/validation/online-map-836'; output.mkdir(parents=True,exist_ok=True)
        from PIL import ImageGrab
        settle(root,3)
        ImageGrab.grab(bbox=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height())).save(output/'parcel-preview.png')
        assert w.last_preview_point == PARCEL['coordinates'], f'Parcel preview missing: loaded={w.loaded}, embedded={w.embedded}, status={w.status.get()}, errors={errors}'
        w.save_found(); settle(root)
        saved=model.record(M,'project',ids['target'])
        assert saved['map_label']==PARCEL['label'] and saved['map_source']=='ruian-parcel'
        # Stale preview cannot overwrite a point changed by another editor.
        with patch.object(online.Client,'parcels',return_value=[PARCEL]):
            w.find_parcel(); wait_job(w)
        model.save_location(M,'project',ids['target'],'49.2,16.6',model.snapshot(saved))
        w.save_found(); assert warnings; warnings.clear()
        assert model.point(M,model.record(M,'project',ids['target'])['gps_coordinates'])==[16.6,49.2]
        w.cadastre_query.set('Jiný katastr')
        assert not w.cadastre_choices and w.preview is None
        assert not errors, errors
        print('8.0.36: real Tk multi-selection, asynchronous batches, parcel preview/save and stale-write rejection OK',flush=True)
    finally:
        w=root.map_workspace; w.cancel_job(quiet=True)
        if w.bridge: w.bridge.close()
        root._turto_closing=True
        for job in root.tk.splitlist(root.tk.call('after','info')): root.tk.call('after','cancel',job)
        root.destroy()


if __name__=='__main__':
    if '--ui-worker' in sys.argv:
        ui_checks(sys.argv[-1]); raise SystemExit(0)
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(LookupTests))
    if not result.wasSuccessful(): raise SystemExit(1)
    if '--live' in sys.argv:
        client=online.Client()
        matches=client.addresses(ADDRESS); assert online.exact_address(ADDRESS,matches)
        ku=client.cadastres('Kobylisy'); assert ku and ku[0]['code']==730475
        parcels=client.parcels(ku[0],'1/2'); assert parcels
        print('Live ČÚZK address, cadastral territory and parcel lookup OK',flush=True)
    if '--source-only' not in sys.argv:
        with tempfile.TemporaryDirectory(prefix='turto-online-ui-') as td:
            subprocess.run([sys.executable,__file__,'--ui-worker',td],check=True,timeout=150)
