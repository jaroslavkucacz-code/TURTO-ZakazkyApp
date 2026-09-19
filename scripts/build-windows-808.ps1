param()
$ErrorActionPreference = 'Stop'
$version = (Get-Content build/windows/version.txt -Raw).Trim()
python scripts/build-map-host.py
if ($LASTEXITCODE -ne 0) { throw 'Embedded map host build failed' }
pyinstaller --noconfirm --clean build/windows/TURTO_CRM.spec
if ($LASTEXITCODE -ne 0) { throw 'Main application build failed' }
pyinstaller --noconfirm --clean build/windows/TURTO_CRM_Updater.spec
if ($LASTEXITCODE -ne 0) { throw 'Updater build failed' }
Copy-Item 'dist/TURTO CRM Updater/TURTO CRM Updater.exe' 'dist/TURTO CRM/TURTO CRM Updater.exe' -Force
Copy-Item 'dist/TURTO CRM Updater/_updater_runtime' 'dist/TURTO CRM/_updater_runtime' -Recurse -Force
$runtimeManifest = [ordered]@{
  version = $version
  channel = 'windows'
  build = 'release'
  updater_format = 'onedir-v1'
  source_commit = $env:GITHUB_SHA
} | ConvertTo-Json
Set-Content 'dist/TURTO CRM/version.json' $runtimeManifest -Encoding utf8
if (-not (Test-Path 'dist/TURTO CRM/TURTO CRM.exe')) { throw 'Main EXE missing' }
if (-not (Test-Path 'dist/TURTO CRM/_updater_runtime')) { throw 'Updater dependencies missing' }
$stage = "dist/TURTO_CRM_$version"
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item 'dist/TURTO CRM' $stage -Recurse
$zip = "dist/TURTO_CRM_Update_$version.zip"
Remove-Item $zip -Force -ErrorAction SilentlyContinue
Compress-Archive -Path $stage -DestinationPath $zip -CompressionLevel Optimal
$candidates = @(
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
  "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
  "$env:ProgramFiles\Inno Setup 7\ISCC.exe"
)
$iscc = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup compiler missing' }
& $iscc "/DMyAppVersion=$version" 'build/windows/TURTO_CRM.iss'
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
$setup = "dist/installer/TURTO_CRM_Setup_$version.exe"
$manifest = [ordered]@{
  format = 'turto-crm-windows-update-v1'
  channel = 'windows'
  version = $version
  package = "TURTO_CRM_Update_$version.zip"
  sha256 = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant()
  installer = "TURTO_CRM_Setup_$version.exe"
  installer_sha256 = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLowerInvariant()
  source_commit = $env:GITHUB_SHA
  updater_format = 'onedir-v1'
} | ConvertTo-Json
Set-Content 'dist/latest-windows.preview.json' $manifest -Encoding utf8
