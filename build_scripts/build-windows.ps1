param(
    [string]$PythonExe = "C:/DevTools/Python311/python.exe"
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$releaseDir = Join-Path $root 'release/windows'

New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null

& $PythonExe -m pip install --upgrade pip | Out-Host
& $PythonExe -m pip install -r (Join-Path $root 'build_scripts/requirements-build.txt') | Out-Host
& $PythonExe -m PyInstaller --clean --noconfirm (Join-Path $root 'sync_skills.spec') | Out-Host

Copy-Item (Join-Path $root 'dist/sync-skills.exe') (Join-Path $releaseDir 'sync-skills.exe') -Force
Write-Host "Windows binary written to $releaseDir/sync-skills.exe"