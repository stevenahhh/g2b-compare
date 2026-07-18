[CmdletBinding()]
param(
    [string]$HomePath = ".g2b",
    [switch]$NoBrowser,
    [switch]$ProvisionOnly,
    [scriptblock]$BrowserLauncher = { param([string]$Url) Start-Process $Url }
)

$ErrorActionPreference = "Stop"
$HostAddress = "127.0.0.1"
$Port = 8765
$ContractPath = Join-Path $HomePath "docs/api-contract-observed.json"

function Invoke-Checked {
    param(
        [string[]]$Arguments,
        [string]$FailureCode
    )
    & uv @Arguments
    if ($LASTEXITCODE -ne 0) { throw $FailureCode }
}

try {
    Invoke-Checked @("sync", "--frozen") "dependency-sync-failed"
    Invoke-Checked @("run", "g2b-compare", "--home", $HomePath, "init-db") "migration-failed"

    & uv run g2b-compare --home $HomePath verify *> $null
    $Ready = $LASTEXITCODE -eq 0
    if (-not $Ready) {
        if ([string]::IsNullOrWhiteSpace($env:G2B_SERVICE_KEY)) {
            throw "missing-service-key"
        }
        if (-not (Test-Path -LiteralPath $ContractPath -PathType Leaf)) {
            if ([string]::IsNullOrWhiteSpace($env:G2B_SECRET_SOURCE)) {
                throw "missing-secret-source"
            }
            Invoke-Checked @(
                "run", "g2b-compare", "--home", $HomePath, "capture-contract"
            ) "contract-capture-failed"
        }
        Invoke-Checked @(
            "run", "g2b-compare", "--home", $HomePath, "sync", "full"
        ) "initial-sync-failed"
        Invoke-Checked @(
            "run", "g2b-compare", "--home", $HomePath, "sync", "attributes",
            "--max-batches", "100"
        ) "attribute-sync-failed"
        if ([string]::IsNullOrWhiteSpace($env:G2B_RELATIONS_WORKBOOK)) {
            throw "missing-relations-workbook"
        }
        if (-not (Test-Path -LiteralPath $env:G2B_RELATIONS_WORKBOOK -PathType Leaf)) {
            throw "relations-workbook-missing"
        }
        Invoke-Checked @(
            "run", "g2b-compare", "--home", $HomePath, "import-relations"
        ) "relation-import-failed"
        Invoke-Checked @(
            "run", "g2b-compare", "--home", $HomePath, "materialize"
        ) "materialization-failed"
        Invoke-Checked @(
            "run", "g2b-compare", "--home", $HomePath, "rebuild-index"
        ) "index-build-failed"
        Invoke-Checked @(
            "run", "g2b-compare", "--home", $HomePath, "precompute"
        ) "precompute-failed"
    }

    Invoke-Checked @(
        "run", "g2b-compare", "--home", $HomePath, "verify"
    ) "verification-failed"
    Invoke-Checked @(
        "run", "g2b-compare", "--home", $HomePath,
        "verify-secrets", "--all-storage"
    ) "secret-verification-failed"
    if ($ProvisionOnly) { exit 0 }

    $Server = Start-Process -FilePath "uv" -WindowStyle Hidden -PassThru -ArgumentList @(
        "run", "g2b-compare", "--home", $HomePath, "serve",
        "--host", $HostAddress, "--port", "$Port"
    )
    try {
        $HttpReady = $false
        foreach ($Attempt in 1..50) {
            if ($Server.HasExited) { throw "server-stopped-before-ready" }
            try {
                Invoke-RestMethod "http://${HostAddress}:${Port}/readyz" | Out-Null
                $HttpReady = $true
                break
            } catch [System.Net.Http.HttpRequestException] {
                Start-Sleep -Milliseconds 100
            } catch [System.Net.WebException] {
                Start-Sleep -Milliseconds 100
            }
        }
        if (-not $HttpReady) { throw "ready-timeout" }
        if (-not $NoBrowser) {
            & $BrowserLauncher "http://${HostAddress}:${Port}/"
        }
        Wait-Process -Id $Server.Id
    } finally {
        if (-not $Server.HasExited) { Stop-Process -Id $Server.Id }
    }
} catch [System.Management.Automation.PipelineStoppedException] {
    exit 130
}
