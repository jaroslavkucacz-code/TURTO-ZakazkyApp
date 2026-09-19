#!/usr/bin/env python3
"""Build the isolated WebView2 host and bundle verified, pinned map assets."""
from __future__ import annotations
import base64
import hashlib
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / 'build/windows/_generated'
HOST = GENERATED / 'map-host'
MAPLIBRE = 'https://registry.npmjs.org/maplibre-gl/-/maplibre-gl-5.6.2.tgz'
MAPLIBRE_SHA512 = 'SEqYThhUCFf6Lm0TckpgpKnto5u4JsdPYdFJb6g12VtuaFsm3nYdBO+fOmnUYddc8dXihgoGnuXvPPooUcRv5w=='
WEBVIEW = 'https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/1.0.4191.47/microsoft.web.webview2.1.0.4191.47.nupkg'
WEBVIEW_SHA256 = 'f492bbf547d0da329553b6727435b677579b1e9f91cc9e4a1ad029366d5f23d0'


def fetch(url, algorithm, expected):
    cache = GENERATED / 'downloads' / url.rsplit('/',1)[1]
    cache.parent.mkdir(parents=True,exist_ok=True)
    data = cache.read_bytes() if cache.is_file() else None
    if data is None:
        with urllib.request.urlopen(url,timeout=90) as response: data = response.read(80_000_001)
    if len(data) > 80_000_000 or hashlib.new(algorithm,data).digest() != expected:
        raise RuntimeError('Dependency integrity mismatch: ' + url)
    cache.write_bytes(data)
    return data


def build():
    HOST.mkdir(parents=True,exist_ok=True)
    assets = HOST / 'assets'; assets.mkdir(exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(fetch(MAPLIBRE,'sha512',base64.b64decode(MAPLIBRE_SHA512)))) as archive:
        for source,target in [('package/dist/maplibre-gl.js','maplibre-gl.js'),
                               ('package/dist/maplibre-gl.css','maplibre-gl.css'),
                               ('package/LICENSE.txt','MAPLIBRE-LICENSE.txt')]:
            with archive.extractfile(source) as stream: (assets/target).write_bytes(stream.read())
    for source in (ROOT / 'ZakazkyApp_base_6.1/price_lists_domain/maps/assets').iterdir():
        if source.is_file(): shutil.copyfile(source,assets/source.name)
    with zipfile.ZipFile(io.BytesIO(fetch(WEBVIEW,'sha256',bytes.fromhex(WEBVIEW_SHA256)))) as archive:
        for source,target in [
            ('lib/net462/Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.Core.dll'),
            ('lib/net462/Microsoft.Web.WebView2.WinForms.dll','Microsoft.Web.WebView2.WinForms.dll'),
            ('runtimes/win-x64/native/WebView2Loader.dll','WebView2Loader.dll'),
            ('LICENSE.txt','WEBVIEW2-LICENSE.txt')]:
            (HOST/target).write_bytes(archive.read(source))
    if sys.platform != 'win32':
        print('Pinned dependencies and map assets verified; native compilation requires Windows.')
        return
    import os
    framework = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319'
    compiler = framework / 'csc.exe'
    command = [str(compiler),'/nologo','/target:winexe','/platform:x64','/optimize+',
               '/out:'+str(HOST/'TURTO Map.exe'), '/r:System.dll','/r:System.Core.dll',
               '/r:System.Drawing.dll','/r:System.Windows.Forms.dll','/r:System.Web.Extensions.dll',
               '/r:'+str(HOST/'Microsoft.Web.WebView2.Core.dll'),
               '/r:'+str(HOST/'Microsoft.Web.WebView2.WinForms.dll'),
               str(ROOT/'build/windows/map-host/MapHost.cs')]
    subprocess.run(command,check=True)
    (HOST/'TURTO Map.exe.config').write_text(
        '<?xml version="1.0"?><configuration><startup><supportedRuntime version="v4.0" sku=".NETFramework,Version=v4.8"/></startup></configuration>',encoding='utf-8')
    print('TURTO Map.exe compiled; MapLibre 5.6.2 and WebView2 1.0.4191.47 checksums verified.')


if __name__ == '__main__': build()
