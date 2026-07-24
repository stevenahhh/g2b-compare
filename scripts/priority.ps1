param(
    [ValidateSet("import", "api", "site", "sync", "status")]
    [string]$Action = "status",
    [int]$MaxCalls = 10000,
    [int]$MaxItems = 0,
    [switch]$Headed
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($env:G2B_SERVICE_KEY)) {
    $envFile = Join-Path $root ".env"
    if (Test-Path -LiteralPath $envFile) {
        foreach ($line in Get-Content -LiteralPath $envFile) {
            if ($line.StartsWith("G2B_SERVICE_KEY=")) {
                $env:G2B_SERVICE_KEY = $line.Substring(16).Trim('"', "'")
                break
            }
        }
    }
}

Push-Location $root
try {
    if ($Action -eq "sync") {
        uv run --no-sync python -m g2b_compare.priority_cli import
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        uv run --no-sync python -m g2b_compare.priority_cli api --max-calls $MaxCalls
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        uv run --no-sync playwright install chromium
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        $arguments = @(
            "run", "--no-sync", "python", "-m", "g2b_compare.priority_cli",
            "site", "--max-items", $MaxItems
        )
        if ($Headed) { $arguments += "--headed" }
        & uv @arguments
        exit $LASTEXITCODE
    }
    elseif ($Action -eq "api") {
        uv run --no-sync python -m g2b_compare.priority_cli api --max-calls $MaxCalls
    }
    elseif ($Action -eq "site") {
        uv run --no-sync playwright install chromium
        $arguments = @(
            "run", "--no-sync", "python", "-m", "g2b_compare.priority_cli",
            "site", "--max-items", $MaxItems
        )
        if ($Headed) {
            $arguments += "--headed"
        }
        & uv @arguments
    }
    else {
        uv run --no-sync python -m g2b_compare.priority_cli $Action
    }
}
finally {
    Pop-Location
}
