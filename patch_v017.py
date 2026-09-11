from pathlib import Path
import base64,zlib,json
CHUNKS=5

def apply_patch(root):
    root=Path(root)
    enc=''.join((root/f'patch_v017_data_{i}.txt').read_text(encoding='ascii').strip() for i in range(1,CHUNKS+1))
    data=json.loads(zlib.decompress(base64.b64decode(enc)).decode('utf-8'))
    for rel,text in data.items():
        p=root/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text,encoding='utf-8')
    (root/'ZMENY_0.1.7.txt').write_text('TURTO – Měsíční přehledy v0.1.7\n- Dvojklik na Největší doklady otevře detail DL.\n- Detail zobrazuje položky, množství, zisk/jednotku a zisk položky.\n- Připravené sloupce pro budoucí prodejní cenu, náklad a položkovou marži.\n',encoding='utf-8')
