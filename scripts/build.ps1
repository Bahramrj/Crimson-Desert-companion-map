# Build the Windows app: no console, asks for administrator rights (UAC).
#   powershell -ExecutionPolicy Bypass -File scripts\build.ps1 [-SkipWeb] [-Release]
# Default: dist\CompanionMap.exe, one file, for testing.
# -Release: release\CompanionMap\ (a folder: CompanionMap.exe with Qt kept as separate, replaceable
#   files in PySide6\, as the LGPL asks, plus licences and notices) and release\CompanionMap-<version>-win64.zip.
# Needs the .venv from requirements-build.txt. -SkipWeb uses the committed web\dist as is.
param([switch]$SkipWeb, [switch]$Release)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$Build = Join-Path $Root 'build'
if (-not (Test-Path $Py)) { throw "Missing .venv: python -m venv .venv; .venv\Scripts\pip install -r requirements-build.txt" }

function Step($name, [scriptblock]$body) {
    Write-Host "== $name" -ForegroundColor Cyan
    & $body
    if ($LASTEXITCODE) { throw "$name failed (exit $LASTEXITCODE)" }
}

if (-not $SkipWeb) {
    Step 'web: npm ci' { & (Join-Path $PSScriptRoot 'web.ps1') ci --no-fund --no-audit }
    Step 'web: build' { & (Join-Path $PSScriptRoot 'web.ps1') run build }
}
if (-not (Test-Path (Join-Path $Root 'web\dist\index.html'))) { throw 'web\dist is missing; run without -SkipWeb' }
Step 'icon + version info' { & $Py (Join-Path $PSScriptRoot 'build_assets.py') $Build }

$sep = ';'
$data = @(
    "$Root\web\dist${sep}web\dist",
    "$Root\engine\signatures.json${sep}engine",
    "$Root\engine\paths${sep}engine\paths"
) | ForEach-Object { '--add-data', $_ }
$layout = @(if ($Release) { '--onedir', '--contents-directory', '.' } else { '--onefile' })     # always an array, so @layout splats it
$dist = if ($Release) { Join-Path $Root 'release' } else { Join-Path $Root 'dist' }
Step 'PyInstaller' {
    Push-Location $Root
    try {
        & $Py -m PyInstaller --noconfirm --clean @layout --windowed --uac-admin `
            --name CompanionMap `
            --icon (Join-Path $Build 'companionmap.ico') `
            --version-file (Join-Path $Build 'version_info.txt') `
            --distpath $dist --workpath (Join-Path $Build 'pyi') --specpath $Build `
            @data `
            --exclude-module pytest --exclude-module playwright --exclude-module PySide6.QtQml `
            (Join-Path $PSScriptRoot 'companionmap_entry.py')
    } finally { Pop-Location }
}
if (-not $Release) {
    $exe = Get-Item (Join-Path $Root 'dist\CompanionMap.exe')
    Write-Host ("Built {0} ({1:N1} MB)" -f $exe.FullName, ($exe.Length / 1MB)) -ForegroundColor Green
    return
}

# release: licences and notices next to the exe, Qt's licences inside PySide6\, then the zip
$app = Join-Path $dist 'CompanionMap'
$qt = Join-Path $app 'PySide6'
if (-not (Test-Path $qt)) { throw "PySide6 folder missing in $app" }
$qtLicences = New-Item -ItemType Directory -Force (Join-Path $qt 'LICENSES')
Copy-Item (Join-Path $Root 'licenses\LGPL-3.0.txt'), (Join-Path $Root 'licenses\GPL-3.0.txt') $qtLicences
Copy-Item (Join-Path $Root 'licenses\README-PySide6.txt') (Join-Path $qtLicences 'README.txt')
Copy-Item (Join-Path $Root 'README.md'), (Join-Path $Root 'THIRD_PARTY_NOTICES.md') $app
Copy-Item (Join-Path $Root 'gamedata\NOTICE.md') (Join-Path $app 'NOTICE-gamedata.md')
if (Test-Path (Join-Path $Root 'LICENSE')) { Copy-Item (Join-Path $Root 'LICENSE') $app }
$version = & $Py -c "import sys; sys.path.insert(0, r'$Root'); from server import __version__; print(__version__)"
$zip = Join-Path $dist "CompanionMap-$version-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $app -DestinationPath $zip
$size = (Get-ChildItem $app -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("Built {0} ({1:N1} MB) and {2} ({3:N1} MB)" -f $app, ($size / 1MB), $zip, ((Get-Item $zip).Length / 1MB)) -ForegroundColor Green
