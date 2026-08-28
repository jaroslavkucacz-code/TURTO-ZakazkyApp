import sys,os,time,zipfile,shutil,tempfile,subprocess
from pathlib import Path

STALE_ROOT_FILES={
    'crm_features.py','crm_runtime.py','crm_v605.py','post_baseline.py','post_fix_613.py',
    'v606_features.py','v608_stability.py','v611_audit.py','v613_ui.py','v614_next.py',
    'v615_input.py','v616_stability.py','v617_offerhub.py','v618_inputfix.py','v619_fixes.py',
    'v620_outlookdrop.py','v621_prices.py','v622_palette.py','v623_exports.py','v624_legacy_exports.py',
    'v625_stability.py','v626_smoothui.py','v627_fastui_dropfix.py','v628_modernui_resize.py',
    'v630_safeofferdrop.py','v631_diskdrop.py','v632_offerlinks.py','v633_offerassign_deadlines.py',
    'v634_assignment_search.py','v635_actions_sort.py','v636_action_offers_stabletable.py',
    'v637_project_offer_model.py','v638_table_updatefix.py','v640_warning_cleanup.py',
    'v641_fill_tables.py','v642_exact_table_fill.py','v644_default_date_sort.py','v645_project_table_fill.py',
    'Spustit_Zakazky_v5.bat','Spustit_Zakazky_v5.vbs','Spustit_DIAGNOSTIKA.bat','Spustit_Qt_PREVIEW.bat',
    'Vytvorit_EXE.bat','Vytvorit_manifest_aktualizace.py','latest.example.json'
}


def main():
    if len(sys.argv)<4:return
    package=Path(sys.argv[1]);target=Path(sys.argv[2]);pid=int(sys.argv[3])
    for _ in range(120):
        try:
            os.kill(pid,0);time.sleep(.25)
        except Exception:break
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        with zipfile.ZipFile(package) as z:z.extractall(td)
        roots=[p for p in td.iterdir() if p.is_dir()]
        src=roots[0] if len(roots)==1 else td

        # Od 6.3 jsou historické runtime moduly uvnitř _runtime. Při přechodu ze
        # starší instalace proto odstraň staré kopie jen z kořene programu.
        # Uživatelská data jsou mimo instalační adresář v Dokumenty/TURTO Zakazky.
        for name in STALE_ROOT_FILES:
            p=target/name
            try:
                if p.is_file() or p.is_symlink():p.unlink()
            except Exception:pass
        for d in ('ZakazkyApp_v5.7','original_source'):
            try:shutil.rmtree(target/d,ignore_errors=True)
            except Exception:pass

        for p in src.rglob('*'):
            rel=p.relative_to(src)
            if '__pycache__' in rel.parts:continue
            if p.is_dir():
                (target/rel).mkdir(parents=True,exist_ok=True);continue
            if p.name=='v5_error.log':continue
            dest=target/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            try:shutil.copy2(p,dest)
            except Exception:
                time.sleep(.5);shutil.copy2(p,dest)

    # 6.3 používá jediný aktuální spouštěč.
    vbs=target/'Spustit_Zakazky.vbs'
    if sys.platform.startswith('win') and vbs.exists():
        subprocess.Popen(['wscript.exe',str(vbs)],cwd=str(target))
    else:
        subprocess.Popen([sys.executable,str(target/'ZakazkyCRM.pyw')],cwd=str(target))

if __name__=='__main__':
    try:main()
    except Exception as e:
        try:(Path(sys.argv[2])/'update_error.log').write_text(str(e),encoding='utf-8')
        except Exception:pass
