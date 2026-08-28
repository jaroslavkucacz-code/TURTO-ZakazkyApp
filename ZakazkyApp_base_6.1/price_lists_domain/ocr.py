"""Local Windows OCR and PDF rendering."""
from __future__ import annotations
import json,os,re,subprocess,tempfile,time
from pathlib import Path
from .common import PriceListImportCancelled

def _read_pdf_text(path: Path) -> tuple[str, list[dict]]:
    import fitz

    text_parts = []
    pages = []
    with fitz.open(str(path)) as document:
        for index, page in enumerate(document):
            text = page.get_text("text") or ""
            words = page.get_text("words") or []
            text_parts.append(text)
            pages.append({
                "page": index + 1,
                "width": float(page.rect.width),
                "height": float(page.rect.height),
                "text": text,
                "words": [
                    {"x0": float(w[0]), "y0": float(w[1]), "x1": float(w[2]), "y1": float(w[3]), "text": str(w[4])}
                    for w in words
                ],
            })
    return "\n".join(text_parts), pages


def _text_is_insufficient(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    alpha = sum(ch.isalpha() for ch in compact)
    numeric = sum(ch.isdigit() for ch in compact)
    return len(compact) < 100 or (alpha + numeric) < 80


def _windows_ocr_image(image_path: Path, language_tag: str = "", pulse=None) -> dict:
    if os.name != "nt":
        raise RuntimeError("Automatické OCR je dostupné ve Windows 10/11.")
    script = r'''
param([string]$ImagePath,[string]$LanguageTag='')
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
if($LanguageTag){
  try{$lang=[Windows.Globalization.Language]::new($LanguageTag);$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)}catch{}
}
if($null -eq $engine){$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()}
if($null -eq $engine){throw 'Windows OCR nemá dostupný jazykový model.'}
$file=Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
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
[pscustomobject]@{language=$engine.RecognizerLanguage.LanguageTag;text=$result.Text;lines=$lines} | ConvertTo-Json -Depth 8 -Compress
'''
    with tempfile.TemporaryDirectory(prefix="turto_ocr_ps_") as td:
        ps1 = Path(td) / "ocr.ps1"
        ps1.write_text(script, encoding="utf-8-sig")
        process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", str(ps1),
             "-ImagePath", str(image_path), "-LanguageTag", language_tag],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        started = time.monotonic()
        while process.poll() is None:
            try:
                if pulse:
                    pulse()
            except BaseException:
                try:process.terminate();process.wait(timeout=2)
                except Exception:
                    try:process.kill()
                    except Exception:pass
                raise
            if time.monotonic() - started > 180:
                try:process.kill()
                except Exception:pass
                raise RuntimeError("Windows OCR překročilo časový limit 180 sekund.")
            time.sleep(0.08)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            raise RuntimeError((stderr or stdout or "Windows OCR selhalo.").strip())
        raw = (stdout or "").lstrip('\ufeff').strip()
        if not raw:
            raise RuntimeError("Windows OCR nevrátilo žádný výsledek.")
        start=raw.find('{');end=raw.rfind('}')
        if start<0 or end<start:
            raise RuntimeError("Windows OCR vrátilo nečitelný výstup.")
        return json.loads(raw[start:end+1])


def _ocr_pdf(path: Path, progress=None) -> tuple[str, list[dict], str]:
    import fitz

    all_text = []
    pages = []
    engine = "Windows.Media.Ocr"
    with tempfile.TemporaryDirectory(prefix="turto_pricelist_ocr_") as td:
        with fitz.open(str(path)) as document:
            total = len(document)
            for index, page in enumerate(document):
                if progress:
                    progress(index, total, f"OCR strany {index + 1} z {total}")
                # Windows.Media.Ocr has a finite maximum image dimension. 210 DPI keeps an A4
                # page below that limit while remaining sharp enough for tabular prices.
                pix = page.get_pixmap(matrix=fitz.Matrix(210 / 72, 210 / 72), alpha=False)
                image = Path(td) / f"page_{index + 1}.png"
                pix.save(str(image))
                result = None
                errors = []
                # Prefer Czech, then the user's Windows profile, German and English.
                # Stop after the first non-trivial result instead of OCR-ing every page
                # four times; unsupported language packs simply fall through.
                for lang in ("cs-CZ", "", "de-DE", "en-US"):
                    try:
                        candidate = _windows_ocr_image(
                            image, lang,
                            (lambda i=index, t=total: progress(i, t, f"OCR strany {i + 1} z {t}")) if progress else None,
                        )
                        if str(candidate.get("text") or "").strip():
                            result = candidate
                            break
                    except PriceListImportCancelled:
                        raise
                    except Exception as exc:
                        errors.append(str(exc))
                if result is None:
                    raise RuntimeError(errors[-1] if errors else "OCR nebylo dostupné.")
                text = str(result.get("text") or "")
                all_text.append(text)
                pages.append({
                    "page": index + 1,
                    "width": pix.width,
                    "height": pix.height,
                    "text": text,
                    "lines": result.get("lines") or [],
                    "language": result.get("language") or "",
                })
    return "\n".join(all_text), pages, engine
