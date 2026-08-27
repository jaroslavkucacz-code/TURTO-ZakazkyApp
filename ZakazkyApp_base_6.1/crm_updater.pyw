import sys,os,time,zipfile,shutil,tempfile,subprocess
from pathlib import Path

def main():
    if len(sys.argv)<4:return
    package=Path(sys.argv[1]);target=Path(sys.argv[2]);pid=int(sys.argv[3])
    for _ in range(120):
        try:
            os.kill(pid,0)
            time.sleep(.25)
        except Exception:
            break
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        with zipfile.ZipFile(package) as z:z.extractall(td)
        roots=[p for p in td.iterdir() if p.is_dir()]
        src=roots[0] if len(roots)==1 else td
        # Programová data jsou v Dokumenty\\TURTO Zakazky; instalační updater tedy
        # může bezpečně nahradit programové soubory. Necháme ale lokální logy.
        for p in src.rglob("*"):
            rel=p.relative_to(src)
            if any(part in ("__pycache__",) for part in rel.parts):continue
            if p.is_dir():
                (target/rel).mkdir(parents=True,exist_ok=True)
                continue
            if p.name in ("v5_error.log",):continue
            dest=target/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            try:shutil.copy2(p,dest)
            except Exception:
                time.sleep(.5);shutil.copy2(p,dest)
    # znovu spustit bez konzole
    vbs=target/"Spustit_Zakazky_v5.vbs"
    if sys.platform.startswith("win") and vbs.exists():
        subprocess.Popen(["wscript.exe",str(vbs)],cwd=str(target))
    else:
        subprocess.Popen([sys.executable,str(target/"app.py")],cwd=str(target))

if __name__=="__main__":
    try:main()
    except Exception as e:
        try:(Path(sys.argv[2])/"update_error.log").write_text(str(e),encoding="utf-8")
        except Exception:pass
