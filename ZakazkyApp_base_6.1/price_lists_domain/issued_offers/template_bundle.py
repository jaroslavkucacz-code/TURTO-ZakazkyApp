"""Portable template ZIPs: data and artwork only; no code or archive extraction."""
from __future__ import annotations
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from . import service, template_layout

LIMIT=16*1024*1024


def export_template(M, template, target):
    layout=template_layout.normalize(template.get("layout_json"))
    data=template_layout.validate_geometry(template,layout)
    for key in ("id","builtin_key","created_at","updated_at"):
        data.pop(key,None)
    data["is_default"]=0; data["active"]=1
    payloads={}; hashes={}
    for owner,key in ((data,"header_path"),(data,"footer_path"),(layout,"signature_path")):
        value=owner.get(key)
        if not value: continue
        p=Path(template_layout.asset_path(value))
        if not p.is_file(): raise ValueError(f"Chybí soubor {p.name}.")
        if p.stat().st_size>LIMIT: raise ValueError("Grafika je příliš velká pro export šablony.")
        blob=p.read_bytes();name=f"assets/{len(payloads)}{p.suffix.lower()}"
        payloads[name]=blob;hashes[name]=hashlib.sha256(blob).hexdigest();owner[key]=name
    data["layout_json"]=json.dumps(layout,ensure_ascii=False)
    if sum(map(len,payloads.values()))>LIMIT: raise ValueError("Grafika překračuje 16 MB.")
    fd,tmp=tempfile.mkstemp(suffix=".zip",dir=str(Path(target).parent));os.close(fd)
    try:
        with zipfile.ZipFile(tmp,"w",zipfile.ZIP_DEFLATED) as z:
            z.writestr("template.json",json.dumps({"format":"TURTO-PDF-template","version":1,"template":data,"sha256":hashes},ensure_ascii=False,indent=2))
            for name,blob in payloads.items(): z.writestr(name,blob)
        os.replace(tmp,target)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def import_template(M, path):
    with zipfile.ZipFile(path) as z:
        entries=z.infolist();names=[e.filename for e in entries]
        if len(entries)>10 or len(set(names))!=len(names) or sum(e.file_size for e in entries)>LIMIT:
            raise ValueError("Balíček šablony je příliš velký nebo obsahuje duplicity.")
        for name in names:
            if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts or "\\" in name:
                raise ValueError("Balíček obsahuje nepovolenou cestu.")
        if "template.json" not in names: raise ValueError("Chybí template.json.")
        manifest=json.loads(z.read("template.json"))
        if manifest.get("format")!="TURTO-PDF-template" or manifest.get("version")!=1:
            raise ValueError("Nepodporovaný formát balíčku šablony.")
        data=dict(manifest["template"])
        layout=template_layout.normalize(data.get("layout_json"))
        data=template_layout.validate_geometry(data,layout)
        payloads=[]
        for owner,key in ((data,"header_path"),(data,"footer_path"),(layout,"signature_path")):
            name=owner.get(key)
            if not name: continue
            p=PurePosixPath(str(name))
            if not str(name).startswith("assets/") or p.suffix.lower() not in {".png",".jpg",".jpeg",".pdf"} or name not in names:
                raise ValueError("Šablona obsahuje neplatný grafický soubor.")
            blob=z.read(name)
            if hashlib.sha256(blob).hexdigest()!=manifest.get("sha256",{}).get(name):
                raise ValueError("Kontrolní součet grafiky nesouhlasí.")
            # Validate graphic decoding before creating files or a database row.
            import fitz
            with fitz.open(stream=blob,filetype=p.suffix.lstrip(".")) as image:
                if not image.page_count: raise ValueError("Prázdná grafika.")
            payloads.append((owner,key,p.suffix,blob))
    for owner,key,suffix,blob in payloads:
        target=service.template_assets_root(M)/("import_"+hashlib.sha256(blob).hexdigest()+suffix)
        if not target.exists(): target.write_bytes(blob)
        owner[key]=str(target)
    data["layout_json"]=json.dumps(layout,ensure_ascii=False)
    data.update(active=1,is_default=0)
    for k in ("id","builtin_key"): data.pop(k,None)
    used={r["name"] for r in service.list_templates(M,include_inactive=True)}
    base=str(data.get("name") or "Importovaná šablona");name=base;n=1
    while name in used: n+=1;name=f"{base} ({n})"
    data["name"]=name
    return service.save_template(M,data)
