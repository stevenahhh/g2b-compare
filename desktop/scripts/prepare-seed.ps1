param(
    [Parameter(Mandatory = $true)]
    [string] $Source,
    [string] $Target
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($Target)) {
    $Target = Join-Path $PSScriptRoot "..\src-tauri\resources\seed.sqlite3"
}
$sourcePath = (Resolve-Path -LiteralPath $Source).Path
$targetPath = [IO.Path]::GetFullPath($Target)
$targetDirectory = Split-Path -Parent $targetPath

New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
Remove-Item -LiteralPath $targetPath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "$targetPath-shm" -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "$targetPath-wal" -Force -ErrorAction SilentlyContinue

$sqliteTarget = $targetPath.Replace("\", "/").Replace("'", "''")
& sqlite3.exe $sourcePath ".backup '$sqliteTarget'"
if ($LASTEXITCODE -ne 0) {
    throw "SQLite backup failed with exit code $LASTEXITCODE."
}

$sanitize = @"
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;
DELETE FROM estimate_comparisons;
DELETE FROM estimate_lines;
DELETE FROM estimate_drafts;
COMMIT;
PRAGMA wal_checkpoint(TRUNCATE);
VACUUM;
PRAGMA journal_mode = DELETE;
PRAGMA quick_check;
SELECT
    (SELECT COUNT(*) FROM estimate_drafts) AS drafts,
    (SELECT COUNT(*) FROM estimate_lines) AS lines,
    (SELECT COUNT(*) FROM estimate_comparisons) AS comparisons;
"@
& sqlite3.exe $targetPath $sanitize
if ($LASTEXITCODE -ne 0) {
    throw "SQLite seed sanitization failed with exit code $LASTEXITCODE."
}

$targetItem = Get-Item -LiteralPath $targetPath
[pscustomobject]@{
    Source = $sourcePath
    Target = $targetItem.FullName
    Bytes = $targetItem.Length
} | ConvertTo-Json
