# Download a pinned, checksum-verified Node.js into .tools\node (nothing installed system-wide).
# Run once per PC:  powershell -ExecutionPolicy Bypass -File scripts\setup-node.ps1
$ErrorActionPreference = 'Stop'
$Version = 'v24.22.1'
$Name = "node-$Version-win-x64"
$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root '.tools'
$Target = Join-Path $Tools 'node'

if (Test-Path (Join-Path $Target 'node.exe')) {
    $have = & (Join-Path $Target 'node.exe') --version
    if ($have -eq $Version) { Write-Host "Node $Version already in $Target"; exit 0 }
    Remove-Item -Recurse -Force $Target
}
New-Item -ItemType Directory -Force $Tools | Out-Null
$Zip = Join-Path $Tools "$Name.zip"
$Base = "https://nodejs.org/dist/$Version"
Invoke-WebRequest "$Base/$Name.zip" -OutFile $Zip -UseBasicParsing
$Sums = (Invoke-WebRequest "$Base/SHASUMS256.txt" -UseBasicParsing).Content
$Expected = ($Sums -split "`n" | Where-Object { $_ -match "  $Name\.zip$" }) -replace '\s.*$', ''
$Actual = (Get-FileHash $Zip -Algorithm SHA256).Hash.ToLower()
if (-not $Expected -or $Actual -ne $Expected.Trim().ToLower()) {
    Remove-Item $Zip
    throw "Checksum mismatch for $Name.zip (expected $Expected, got $Actual)"
}
Expand-Archive $Zip -DestinationPath $Tools -Force
Move-Item (Join-Path $Tools $Name) $Target
Remove-Item $Zip
Write-Host "Node $Version ready in $Target (sha256 $Actual)"
