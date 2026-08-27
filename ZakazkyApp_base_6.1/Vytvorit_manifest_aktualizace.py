import sys,json,hashlib
from pathlib import Path
if len(sys.argv)<3:
    print("Použití: py Vytvorit_manifest_aktualizace.py 5.8.0 ZakazkyApp_v5.8.zip");raise SystemExit(1)
ver=sys.argv[1];p=Path(sys.argv[2]).resolve()
if not p.exists():raise SystemExit(f"Soubor nenalezen: {p}")
data={"version":ver,"file":p.name,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}
(p.parent/"latest.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
print("Vytvořeno:",p.parent/"latest.json")
