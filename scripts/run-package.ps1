[CmdletBinding()]
param(
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        $PythonCommand = Get-Command py -ErrorAction SilentlyContinue
    }
    if ($PythonCommand) {
        $ScriptsPath = (& $PythonCommand.Source -c "import sysconfig; print(sysconfig.get_path('scripts'))" | Select-Object -Last 1).Trim()
        if ($LASTEXITCODE -eq 0 -and $ScriptsPath -and (Test-Path -LiteralPath (Join-Path $ScriptsPath "uv.exe"))) {
            $env:Path = "$ScriptsPath;$env:Path"
        }
    }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv executable not found. Install with: python -m pip install uv"
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv가 필요함: https://docs.astral.sh/uv/getting-started/installation/"
}

uv sync --frozen
if ($LASTEXITCODE -ne 0) { throw "dependency-sync-failed" }

uv run g2b-compare --home .g2b init-db
if ($LASTEXITCODE -ne 0) { throw "migration-failed" }

Write-Host "server-ready:http://127.0.0.1:$Port/"
Write-Host "lan-url:http://$($env:COMPUTERNAME):$Port/"
uv run g2b-compare --home .g2b serve --host 0.0.0.0 --port $Port
