# Run npm for web\ with the project's portable Node.  Examples:
#   scripts\web.ps1 ci            install exact dependencies
#   scripts\web.ps1 run build     type-check and build web\dist
#   scripts\web.ps1 run dev       Vite dev server (proxies /cdlm to the Python server on :8788)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Node = Join-Path $Root '.tools\node'
if (-not (Test-Path (Join-Path $Node 'npm.cmd'))) { & (Join-Path $PSScriptRoot 'setup-node.ps1') }
$env:PATH = "$Node;$env:PATH"
Push-Location (Join-Path $Root 'web')
try { & (Join-Path $Node 'npm.cmd') @args; exit $LASTEXITCODE } finally { Pop-Location }
