"""Fast local Windows OCR with page cache and responsive cancellation.

Version 6.3.29 started a new PowerShell/WinRT pipeline for every language and every
page.  A two-page scan could therefore launch up to eight expensive processes.
This implementation renders at a practical 170 DPI, chooses the OCR language once,
processes all missing pages in one PowerShell process and persists each completed
page immediately.  A cancelled import can continue from the cached pages later.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

PROFILE = "winocr-fast-v3-170dpi"
DPI = 170


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _cached_pages(M, source_hash: str):
    with M.db() as con:
        rows = con.execute(
            """SELECT page_no,text,layout_json,language,width,height,elapsed_ms
               FROM price_list_ocr_cache WHERE source_hash=? AND profile=? ORDER BY page_no""",
            (source_hash, PROFILE),
        ).fetchall()
    result = {}
    for row in rows:
        try:
            layout = json.loads(row["layout_json"] or "{}")
        except Exception:
            layout = {}
        layout.setdefault("page", int(row["page_no"]))
        layout.setdefault("text", row["text"] or "")
        layout.setdefault("language", row["language"] or "")
        layout.setdefault("width", int(row["width"] or 0))
        layout.setdefault("height", int(row["height"] or 0))
        result[int(row["page_no"])] = layout
    return result


def _store_page(M, source_hash: str, record: dict) -> None:
    page = int(record.get("page") or 0)
    if page <= 0:
        return
    layout = {
        "page": page,
        "width": int(record.get("width") or 0),
        "height": int(record.get("height") or 0),
        "text": str(record.get("text") or ""),
        "lines": record.get("lines") or [],
        "language": str(record.get("language") or ""),
    }
    with M.db() as con:
        con.execute(
            """INSERT INTO price_list_ocr_cache(
                   source_hash,page_no,profile,text,layout_json,language,width,height,elapsed_ms,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(source_hash,page_no,profile) DO UPDATE SET
                 text=excluded.text,layout_json=excluded.layout_json,language=excluded.language,
                 width=excluded.width,height=excluded.height,elapsed_ms=excluded.elapsed_ms,
                 created_at=CURRENT_TIMESTAMP""",
            (
                source_hash, page, PROFILE, layout["text"],
                json.dumps(layout, ensure_ascii=False, separators=(",", ":")),
                layout["language"], layout["width"], layout["height"],
                int(record.get("elapsed_ms") or 0),
            ),
        )


_POWERSHELL = r'''
param(
  [string]$ManifestPath,
  [string]$OutputPath,
  [string]$ProgressPath
)
$ErrorActionPreference='Stop'
$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null=[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null=[Windows.Storage.FileAccessMode,Windows.Storage,ContentType=WindowsRuntime]
$null=[Windows.Storage.Streams.IRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrEngine,Windows.Media.Ocr,ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrResult,Windows.Media.Ocr,ContentType=WindowsRuntime]
$null=[Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime]
$asTaskGeneric=([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]
function Await($WinRtTask,[type]$ResultType){
  $asTask=$asTaskGeneric.MakeGenericMethod($ResultType)
  $task=$asTask.Invoke($null,@($WinRtTask))
  $task.Wait()
  return $task.Result
}
$engine=$null
try {
  $lang=[Windows.Globalization.Language]::new('cs-CZ')
  $engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
} catch {}
if($null -eq $engine){$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()}
if($null -eq $engine){throw 'Windows OCR nemá dostupný jazykový model.'}
$items=@(Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json)
$utf8=[Text.UTF8Encoding]::new($false)
$done=0
foreach($item in $items){
  $started=[Diagnostics.Stopwatch]::StartNew()
  $file=Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync([string]$item.path)) ([Windows.Storage.StorageFile])
  $stream=Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $decoder=Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap=Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $result=Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
  $lines=@()
  foreach($line in $result.Lines){
    $words=@()
    foreach($word in $line.Words){
      $r=$word.BoundingRect
      $words += [pscustomobject]@{text=$word.Text;x=[double]$r.X;y=[double]$r.Y;w=[double]$r.Width;h=[double]$r.Height}
    }
    $lines += [pscustomobject]@{text=$line.Text;words=$words}
  }
  $started.Stop()
  $record=[pscustomobject]@{
    page=[int]$item.page
    width=[int]$item.width
    height=[int]$item.height
    language=$engine.RecognizerLanguage.LanguageTag
    text=$result.Text
    lines=$lines
    elapsed_ms=[int]$started.ElapsedMilliseconds
  }
  $json=$record | ConvertTo-Json -Depth 9 -Compress
  [IO.File]::AppendAllText($OutputPath,$json+"`n",$utf8)
  $done++
  [IO.File]::WriteAllText($ProgressPath,[string]$done,$utf8)
  try{$stream.Dispose()}catch{}
}
'''


def fast_ocr_pdf(M, path: Path, progress=None):
    if os.name != "nt":
        raise RuntimeError("Automatické OCR Ceníků je dostupné ve Windows 10/11.")
    path = Path(path)
    source_hash = _hash(path)
    try:
        import fitz
    except Exception as exc:
        raise RuntimeError("Pro zpracování PDF chybí knihovna PyMuPDF.") from exc

    cached = _cached_pages(M, source_hash)
    with fitz.open(str(path)) as document:
        total = len(document)
        missing = [index + 1 for index in range(total) if index + 1 not in cached]
        if not missing:
            pages = [cached[index] for index in range(1, total + 1)]
            if progress:
                progress(total, total, f"OCR načteno z mezipaměti ({total} stran)")
            return "\n".join(str(page.get("text") or "") for page in pages), pages, "Windows.Media.Ocr – cache"

        with tempfile.TemporaryDirectory(prefix="turto_pricelist_ocr_") as td:
            folder = Path(td)
            manifest = []
            for ordinal, page_no in enumerate(missing, 1):
                if progress:
                    progress(len(cached) + ordinal - 1, total, f"Připravuji OCR strany {page_no} z {total}")
                page = document[page_no - 1]
                pix = page.get_pixmap(matrix=fitz.Matrix(DPI / 72, DPI / 72), alpha=False, colorspace=fitz.csGRAY)
                image_path = folder / f"page_{page_no:04d}.png"
                pix.save(str(image_path))
                manifest.append({"page": page_no, "path": str(image_path), "width": pix.width, "height": pix.height})

            manifest_path = folder / "manifest.json"
            output_path = folder / "result.jsonl"
            progress_path = folder / "progress.txt"
            script_path = folder / "ocr_batch.ps1"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            script_path.write_text(_POWERSHELL, encoding="utf-8-sig")

            process = subprocess.Popen(
                [
                    "powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass",
                    "-File", str(script_path), "-ManifestPath", str(manifest_path),
                    "-OutputPath", str(output_path), "-ProgressPath", str(progress_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            consumed: set[int] = set()

            def consume_output():
                if not output_path.exists():
                    return
                try:
                    lines = output_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
                except Exception:
                    return
                for raw in lines:
                    try:
                        record = json.loads(raw)
                        page_no = int(record.get("page") or 0)
                    except Exception:
                        continue
                    if page_no <= 0 or page_no in consumed:
                        continue
                    consumed.add(page_no)
                    _store_page(M, source_hash, record)
                    cached[page_no] = {
                        "page": page_no,
                        "width": int(record.get("width") or 0),
                        "height": int(record.get("height") or 0),
                        "text": str(record.get("text") or ""),
                        "lines": record.get("lines") or [],
                        "language": str(record.get("language") or ""),
                    }

            started = time.monotonic()
            timeout = max(90, 45 * len(missing))
            try:
                while process.poll() is None:
                    consume_output()
                    done = len(cached)
                    if progress:
                        progress(done, total, f"Rychlé OCR: hotovo {done} z {total} stran")
                    if time.monotonic() - started > timeout:
                        raise RuntimeError(f"OCR překročilo bezpečný limit {timeout} sekund.")
                    time.sleep(0.10)
            except BaseException:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except Exception:
                    try:process.kill()
                    except Exception:pass
                consume_output()
                raise

            stdout, stderr = process.communicate()
            consume_output()
            if process.returncode != 0:
                detail = (stderr or stdout or "Windows OCR selhalo.").strip()
                raise RuntimeError(detail[-1500:])
            if any(page_no not in cached for page_no in range(1, total + 1)):
                missing_text = [str(page_no) for page_no in range(1, total + 1) if page_no not in cached]
                raise RuntimeError("OCR nevrátilo výsledek pro strany: " + ", ".join(missing_text))

    pages = [cached[index] for index in range(1, total + 1)]
    if progress:
        progress(total, total, f"OCR dokončeno ({total} stran, výsledek je uložen v mezipaměti)")
    return "\n".join(str(page.get("text") or "") for page in pages), pages, "Windows.Media.Ocr – rychlé OCR"


def test_ocr(M, app) -> None:
    value = M.filedialog.askopenfilename(parent=app, title="Otestovat OCR na PDF", filetypes=[("PDF", "*.pdf")])
    if not value:
        return
    state = {"cancel": False}
    win = M.tk.Toplevel(app)
    win.title("Test OCR")
    win.transient(app)
    win.geometry("620x210")
    frame = M.ttk.Frame(win, padding=18)
    frame.pack(fill="both", expand=True)
    label = M.ttk.Label(frame, text="Připravuji test…", style="Section.TLabel")
    label.pack(anchor="w")
    detail = M.ttk.Label(frame, text=Path(value).name, style="PageSubtitle.TLabel")
    detail.pack(anchor="w", pady=(5, 10))
    bar = M.ttk.Progressbar(frame, mode="determinate", maximum=1)
    bar.pack(fill="x")

    def cancel():
        state["cancel"] = True
        detail.configure(text="Storno – ukončuji OCR…")

    M.ttk.Button(frame, text="Storno", command=cancel).pack(anchor="e", pady=(12, 0))
    win.protocol("WM_DELETE_WINDOW", cancel)
    started = time.monotonic()

    def pulse(index, total, text):
        if state["cancel"]:
            from ..common import PriceListImportCancelled
            raise PriceListImportCancelled("Test OCR byl zrušen.")
        label.configure(text=text)
        bar.configure(maximum=max(1, total), value=min(index, total))
        app.update()

    try:
        text, pages, engine = fast_ocr_pdf(M, Path(value), pulse)
        elapsed = time.monotonic() - started
        win.destroy()
        M.messagebox.showinfo(
            "Test OCR",
            f"OCR funguje.\n\nEngine: {engine}\nStran: {len(pages)}\nRozpoznaných znaků: {len(text)}\nČas: {elapsed:.1f} s\n\n"
            "Při dalším načtení stejného souboru se použije mezipaměť.",
            parent=app,
        )
    except Exception as exc:
        try:win.destroy()
        except Exception:pass
        if state["cancel"]:
            return
        M.messagebox.showerror("Test OCR", str(exc), parent=app)


def install(M) -> None:
    from .. import ocr as ocr_module
    from .. import pdf_router

    def patched(path, progress=None):
        return fast_ocr_pdf(M, Path(path), progress)

    ocr_module._ocr_pdf = patched
    pdf_router._ocr_pdf = patched
    M.test_price_list_ocr = lambda app=None: test_ocr(M, app or M._default_root)
