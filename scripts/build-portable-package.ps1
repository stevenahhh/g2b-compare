[CmdletBinding()]
param(
    [string]$OutputPath = "dist\g2b-compare-portable-20260724.zip"
)

$ErrorActionPreference = "Stop"
$Workspace = (Get-Location).Path
$Stage = Join-Path $Workspace "tmp\portable-package-20260724"
$Archive = Join-Path $Workspace $OutputPath
$ArchiveParent = Split-Path -Parent $Archive
if (-not [string]::IsNullOrWhiteSpace($ArchiveParent)) {
    New-Item -ItemType Directory -Path $ArchiveParent -Force | Out-Null
}

if (Test-Path -LiteralPath $Stage) {
    $ResolvedStage = (Resolve-Path -LiteralPath $Stage).Path
    if (-not $ResolvedStage.StartsWith($Workspace, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "unsafe-stage-path"
    }
    Remove-Item -LiteralPath $ResolvedStage -Recurse -Force
}
if (Test-Path -LiteralPath $Archive) {
    Remove-Item -LiteralPath $Archive -Force
}

New-Item -ItemType Directory -Path $Stage -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $Stage "src") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $Stage "scripts") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $Stage "docs") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $Stage ".g2b\docs") -Force | Out-Null

Copy-Item -LiteralPath "pyproject.toml","uv.lock",".python-version","README.md","DESIGN.md" -Destination $Stage
Copy-Item -LiteralPath "scripts\run-package.ps1","scripts\build-portable-package.ps1","scripts\logout-local.bat" -Destination (Join-Path $Stage "scripts")
Copy-Item -LiteralPath "docs\portable-package.md" -Destination (Join-Path $Stage "docs")
Copy-Item -LiteralPath "src\g2b_compare" -Destination (Join-Path $Stage "src") -Recurse
Copy-Item -LiteralPath ".g2b\g2b.sqlite3" -Destination (Join-Path $Stage ".g2b")
Copy-Item -LiteralPath ".g2b\docs\api-contract-observed.json" -Destination (Join-Path $Stage ".g2b\docs")

Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Archive -CompressionLevel Optimal
Get-Item -LiteralPath $Archive | Select-Object FullName,Length
