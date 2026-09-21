"""Isolated PDF layout worker. It receives snapshots and never opens the CRM DB."""
from concurrent.futures import ThreadPoolExecutor
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

def render(payload):
    from price_lists_domain.issued_offers import corporate_renderer
    from v710_cleanup import group_offer_items
    document,items,template=payload['document'],payload['items'],payload['template']
    images=payload.get('images',{})
    for i,item in enumerate(items):
        if str(i) in images:item['_image_bytes']=base64.b64decode(images[str(i)])
    dates=payload.get('dates',{})
    M=SimpleNamespace(fmt_date=lambda value:dates.get(str(value),str(value or '')),group_issued_offer_items=group_offer_items)
    with tempfile.TemporaryDirectory(prefix='turto_preview_worker_') as td:
        path=Path(td)/'preview.pdf'
        result=corporate_renderer.render(M,document,items,dict(template,_preview_fast=True),path)
        return dict(pdf=base64.b64encode(path.read_bytes()).decode('ascii'),regions=result['regions'],group_regions=result['group_regions'])


def main(directory):
    directory=Path(directory)
    request=directory/'request.json';reply=directory/'reply.json'
    while directory.is_dir():
        if not request.exists():
            time.sleep(.02);continue
        try:
            payload=json.loads(request.read_text(encoding='utf-8'));request.unlink()
            result=render(payload)
        except Exception as exc:result={'error':str(exc)}
        target=directory/'reply.tmp'
        target.write_text(json.dumps(result,ensure_ascii=True),encoding='utf-8')
        target.replace(reply)


class Worker:
    def __init__(self):
        self.process=None
        self.closed=False
        self.temp=tempfile.TemporaryDirectory(prefix='turto_preview_channel_')
        self.directory=Path(self.temp.name)
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='offer-preview')

    def submit(self,payload):
        return self.executor.submit(self.exchange,payload)

    def exchange(self,payload):
        if self.closed:raise RuntimeError('Náhled byl zavřen.')
        if self.process is None or self.process.poll() is not None:
            command=([sys.executable,'--pdf-preview-worker'] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).resolve())])+[str(self.directory)]
            self.process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if self.closed:
                self.process.terminate();raise RuntimeError('Náhled byl zavřen.')
        request=self.directory/'request.tmp';reply=self.directory/'reply.json'
        reply.unlink(missing_ok=True)
        request.write_text(json.dumps(payload,ensure_ascii=True),encoding='utf-8')
        request.replace(self.directory/'request.json')
        deadline=time.monotonic()+90
        while not self.closed and self.process.poll() is None and time.monotonic()<deadline:
            if reply.exists():
                result=json.loads(reply.read_text(encoding='utf-8'));reply.unlink()
                if result.get('error'):raise ValueError(result['error'])
                result['pdf']=base64.b64decode(result['pdf'])
                return result
            time.sleep(.02)
        if self.process.poll() is None:self.process.terminate()
        raise RuntimeError('Pomocný proces náhledu se ukončil. Obnovte náhled.')

    def close(self):
        self.closed=True
        if self.process is not None and self.process.poll() is None:self.process.terminate()
        self.executor.shutdown(wait=False,cancel_futures=True)
        # Child termination and file IO can overlap with window closing.
        def cleanup():
            try:
                if self.process is not None:self.process.wait(timeout=10)
                self.temp.cleanup()
            except (OSError,subprocess.TimeoutExpired):pass
        import threading
        threading.Thread(target=cleanup,daemon=True,name='preview-cleanup').start()


def payload(M,document,items,template):
    """Capture directory-free artwork while still on the owner's DB thread."""
    from . import offer_images,template_layout
    from contextlib import closing
    import copy
    data=dict(document=copy.deepcopy(document),items=copy.deepcopy(items),template=copy.deepcopy(template),images={},
              dates={str(document.get(k)):M.fmt_date(document.get(k)) for k in ('issue_date','valid_to')})
    layout=template_layout.normalize(template.get('layout_json'))
    if layout['show_images']:
        with closing(M.db()) as con:
            cache={}
            for i,item in enumerate(items):
                key=(item.get('image_file_snapshot'),item.get('image_asset_key_snapshot'),item.get('source_supplier_offer_item_id'))
                if key not in cache:cache[key]=offer_images.resolve(M,item,con)
                if cache[key]:data['images'][str(i)]=base64.b64encode(cache[key]).decode('ascii')
    for item in data['items']:item.pop('_image_bytes',None)
    return data


def smoke(M):
    from .template_settings import sample_offer
    from .template_layout import builtin_template
    import fitz
    document,items=sample_offer();worker=Worker()
    try:
        result=worker.submit(payload(M,document,items,builtin_template())).result(timeout=35)
        with fitz.open(stream=result['pdf'],filetype='pdf') as pdf:
            assert pdf.page_count and result['regions'] and result['group_regions']
            return dict(pages=pdf.page_count,rows=len(result['regions']),isolated=True)
    finally:worker.close()


if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    main(sys.argv[1])
