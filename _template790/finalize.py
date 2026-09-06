"""One-time transport recovery. Never part of the installed application."""
from pathlib import Path
import base64
import hashlib
import io
import json
import lzma
import subprocess
import tarfile
import tempfile
import zlib

root = Path('.').resolve()
manifest = json.loads((root / '_template790/manifest.json').read_text(encoding='utf-8'))
parts = sorted((root / '.old-template790/_template_workbench').glob('part*.b64'))
assert len(parts) == 4
compressed = base64.b64decode(''.join(p.read_text(encoding='utf-8').strip() for p in parts), validate=True)
assert hashlib.sha256(compressed).hexdigest() == '5d3e8e198c6fc687756bdfde5e099a1e7601a890e305725aeb1b11b493c6a14a'
raw = lzma.LZMADecompressor().decompress(compressed)
patch = header = footer_prefix = None
with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
    for member in archive:
        if member.name == 'changes.patch':
            patch = archive.extractfile(member).read()
        elif member.name == 'turto_offer_header.jpg':
            header = archive.extractfile(member).read()
        elif member.name == 'turto_offer_footer.jpg':
            footer_prefix = raw[member.offset_data:member.offset_data+member.size]
            break
assert patch and header and footer_prefix
assert hashlib.sha256(patch).hexdigest() == '73c539a4a0b35fb57206dea74d8b1d603d57634ccf52f8f265fbc2e47300fa36'
# Correct a single transport transcription character; the original binary is
# accepted only after its full source SHA-256 verifies below.
tail64 = (root / '_template790/footer_tail.z64').read_text(encoding='utf-8').strip()
tail64 = tail64.replace('DfjewUeZtZ5yKwzp', 'DfjewUeZtZ5Kwzp', 1)
footer = footer_prefix + zlib.decompress(base64.b64decode(tail64, validate=True))
assert len(footer) == 21018
assert hashlib.sha256(footer).hexdigest() == '4ba2ac34e25f3a9d4496322e4053ff7f91e2d3eb557d712041b5c52e74fa5c56'
assert hashlib.sha256(header).hexdigest() == '5cba9ba1a6fd3f22ac8208f54b30e59f0c443e5677b9a230c174da017ef0b9b9'
with tempfile.NamedTemporaryFile(suffix='.patch') as handle:
    handle.write(patch); handle.flush()
    subprocess.run(['git', 'apply', '--check', handle.name], check=True)
    subprocess.run(['git', 'apply', handle.name], check=True)
base = root / 'ZakazkyApp_base_6.1/price_lists_domain/issued_offers'
(base / 'assets/turto_offer_header.jpg').write_bytes(header)
(base / 'assets/turto_offer_footer.jpg').write_bytes(footer)

for file in (base/'template_layout.py',base/'professional_workflow.py',root/'TEMPLATE_LAYOUT_7.9.md',root/'release_notes.txt'):
    text=file.read_text(encoding='utf-8');text=text.replace('TURTO – firemní nabídka','TURTO – Standard');file.write_text(text,encoding='utf-8')
p=base/'template_settings.py';s=p.read_text(encoding='utf-8')
s=s.replace('def __init__(self,M,app):','def __init__(self,M,app,preview_document=None,preview_items=None):',1)
s=s.replace('        self.M,self.app=M,app\n','        self.M,self.app=M,app\n        self.preview_document=copy.deepcopy(preview_document) if preview_document is not None else None\n        self.preview_items=copy.deepcopy(preview_items or [])\n',1)
s=s.replace('text="Náhled šablony – ukázková data"','text="Náhled aktuální nabídky – bez uložení" if self.preview_document is not None else "Náhled šablony – ukázková data"',1)
s=s.replace('            data=self.values();doc,items=sample_offer()','            data=self.values()\n            doc,items=(copy.deepcopy(self.preview_document),copy.deepcopy(self.preview_items)) if self.preview_document is not None else sample_offer()\n            if not doc.get("document_number"): doc["document_number"]="NÁHLED NABÍDKY"',1)
s=s.replace('def manage_templates(M,app):\n    return TemplateEditor(M,app)','def manage_templates(M,app,preview_document=None,preview_items=None):\n    return TemplateEditor(M,app,preview_document,preview_items)',1)
p.write_text(s,encoding='utf-8')
p=base/'editor.py';s=p.read_text(encoding='utf-8');s=s.replace('        dialog = manage_templates(self.M, self.win)','        dialog = manage_templates(self.M, self.win, preview_document=self.collect(), preview_items=self.items)',1);p.write_text(s,encoding='utf-8')
p=base/'professional_workflow.py';s=p.read_text(encoding='utf-8');s=s.replace('Náhled používá stejný generátor jako finální PDF. Jde o ukázkové údaje, nikoli o novou vydanou nabídku; nevzniká číslo ani revize.','Náhled používá stejný generátor jako finální PDF. Při otevření přes Upravit šablony v editoru nabídky vidíte přímo aktuální položky, ceny a obrázky této nabídky, včetně dosud neuložených úprav. Při otevření ze záložky Vydané nabídky se zobrazí označené ukázkové údaje. Náhled nikdy nezaloží číslo ani revizi a nemění obchodní data.');p.write_text(s,encoding='utf-8')
p=root/'scripts/validate-7900-runtime-integration.py';s=p.read_text(encoding='utf-8');s=s.replace('doc.update(template_id=tid)','doc.update(template_id=tid, document_number="INTEGRAČNÍ NÁHLED", customer_note="Skutečný neuložený obsah nabídky")',1)
s=s.replace('                    if controller is not None:\n','                    if controller is not None:\n                        assert controller.preview_document["document_number"] == "INTEGRAČNÍ NÁHLED"\n                        assert controller.preview_document["customer_note"] == "Skutečný neuložený obsah nabídky"\n                        assert len(controller.preview_items) == len(items)\n',1);p.write_text(s,encoding='utf-8')
p=root/'release_notes.txt';s=p.read_text(encoding='utf-8');s += '• Při ruční úpravě šablony přímo z nabídky zobrazuje náhled její aktuální položky, obrázky a ceny, nikoli pouze ukázková data. Náhled nevytváří číslo ani PDF revizi.\n';p.write_text(s,encoding='utf-8')

for name, expected in manifest.items():
    actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
    assert actual == expected, (name, actual, expected)
    print('Verified', name, actual)
(root / '.applied790.json').write_text(json.dumps(list(manifest)),encoding='utf-8')
print('All 22 tested source/artwork files restored exactly; no fonts or customer records included.')
