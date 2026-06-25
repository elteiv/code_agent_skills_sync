param()

$ErrorActionPreference = 'Stop'

function Invoke-Docker {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

$root = Split-Path -Parent $PSScriptRoot
$releaseDir = Join-Path $root 'release/linux'
$imageName = 'sync-skills-linux-builder'
$containerName = 'sync-skills-linux-export'
$artifactPath = Join-Path $releaseDir 'sync-skills'

New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null

Invoke-Docker -Arguments @('build', '-t', $imageName, '-f', (Join-Path $root 'build_scripts/Dockerfile.linux-builder'), $root)

try {
    & docker rm -f $containerName 2>$null | Out-Null
} catch {
}

Invoke-Docker -Arguments @('create', '--name', $containerName, $imageName) | Out-Null

try {
    Invoke-Docker -Arguments @('cp', "${containerName}:/workspace/dist/sync-skills", $artifactPath)
} finally {
    & docker rm -f $containerName 2>$null | Out-Null
}

Write-Host "Linux binary written to $artifactPath"