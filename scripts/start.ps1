[CmdletBinding()]
param(
    [string]$HomePath = ".g2b",
    [switch]$NoBrowser,
    [switch]$ProvisionOnly,
    [scriptblock]$BrowserLauncher = { param([string]$Url) Start-Process $Url }
)

$ErrorActionPreference = "Stop"
$BindAddress = "0.0.0.0"
$LoopbackAddress = "127.0.0.1"
$Port = 8765
$ContractPath = Join-Path $HomePath "docs/api-contract-observed.json"
$QuotaStatusPath = Join-Path $HomePath "quota-status.json"
$PinnedContractPath = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "../docs/api-contract-observed.json")
)
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DotenvPath = Join-Path $ProjectRoot ".env"
$ServiceKeyPrefix = "G2B_SERVICE_KEY="

if (
    [string]::IsNullOrWhiteSpace($env:G2B_SERVICE_KEY) -and
    (Test-Path -LiteralPath $DotenvPath -PathType Leaf)
) {
    foreach ($Line in [System.IO.File]::ReadLines($DotenvPath)) {
        if (-not $Line.StartsWith($ServiceKeyPrefix, [System.StringComparison]::Ordinal)) {
            continue
        }
        $ServiceKey = $Line.Substring($ServiceKeyPrefix.Length)
        if (
            $ServiceKey.Length -ge 2 -and
            (
                ($ServiceKey.StartsWith('"') -and $ServiceKey.EndsWith('"')) -or
                ($ServiceKey.StartsWith("'") -and $ServiceKey.EndsWith("'"))
            )
        ) {
            $ServiceKey = $ServiceKey.Substring(1, $ServiceKey.Length - 2)
        }
        if (-not [string]::IsNullOrWhiteSpace($ServiceKey)) {
            $env:G2B_SERVICE_KEY = $ServiceKey
        }
        break
    }
}

function Invoke-Checked {
    param(
        [string[]]$Arguments,
        [string]$FailureCode
    )
    & uv @Arguments
    if ($LASTEXITCODE -ne 0) { throw $FailureCode }
}

function Find-SafeSyncReceipt {
    param([object[]]$SyncOutput)

    foreach ($OutputLine in $SyncOutput) {
        try {
            $Candidate = $OutputLine | ConvertFrom-Json -ErrorAction Stop
        } catch {
            continue
        }
        if (
            $Candidate.status -isnot [string] -or
            $Candidate.error -isnot [string] -or
            $Candidate.status -cne "blocked"
        ) {
            continue
        }
        switch -CaseSensitive ($Candidate.error) {
            "quota-ceiling-exhausted" {
                if (
                    $Candidate.operation -is [string] -and
                    $Candidate.resume_not_before -is [string]
                ) {
                    return [pscustomobject]@{
                        error = "quota-ceiling-exhausted"
                        operation = $Candidate.operation
                        resume_not_before = $Candidate.resume_not_before
                        status = "blocked"
                    }
                }
            }
            "permanent-page-source-failure" {
                return [pscustomobject]@{
                    error = "permanent-page-source-failure"
                    status = "blocked"
                }
            }
            "attempts-exhausted" {
                return [pscustomobject]@{
                    error = "attempts-exhausted"
                    status = "blocked"
                }
            }
        }
    }
    return $null
}

try {
    $ProvisioningDeferred = $false
    Invoke-Checked @("sync", "--frozen") "dependency-sync-failed"
    Invoke-Checked @("run", "g2b-compare", "--home", $HomePath, "init-db") "migration-failed"

    $ErrorActionPreference = "Continue"
    & uv run g2b-compare --home $HomePath verify *> $null
    $Ready = $LASTEXITCODE -eq 0
    $ErrorActionPreference = "Stop"
    if (-not $Ready) {
        if ([string]::IsNullOrWhiteSpace($env:G2B_SERVICE_KEY)) {
            throw "missing-service-key"
        }
        if (-not (Test-Path -LiteralPath $ContractPath -PathType Leaf)) {
            if (Test-Path -LiteralPath $PinnedContractPath -PathType Leaf) {
                New-Item -ItemType Directory -Force -Path (
                    Split-Path -Parent $ContractPath
                ) | Out-Null
                Copy-Item -LiteralPath $PinnedContractPath -Destination $ContractPath
            } else {
                if ([string]::IsNullOrWhiteSpace($env:G2B_SECRET_SOURCE)) {
                    throw "missing-secret-source"
                }
                Invoke-Checked @(
                    "run", "g2b-compare", "--home", $HomePath, "capture-contract"
                ) "contract-capture-failed"
            }
        }
        $ErrorActionPreference = "Continue"
        $SyncOutput = & uv run g2b-compare --home $HomePath sync full 2>&1
        $SyncStatus = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        $Receipt = Find-SafeSyncReceipt -SyncOutput $SyncOutput
        if ($SyncStatus -eq 0) {
            if (Test-Path -LiteralPath $QuotaStatusPath -PathType Leaf) {
                Remove-Item -LiteralPath $QuotaStatusPath
            }
        } elseif (
            $SyncStatus -eq 2 -and
            $null -ne $Receipt -and
            $Receipt.error -ceq "quota-ceiling-exhausted"
        ) {
            New-Item -ItemType Directory -Force -Path $HomePath | Out-Null
            $Receipt | ConvertTo-Json -Compress |
                Set-Content -LiteralPath $QuotaStatusPath -Encoding Ascii
            $ProvisioningDeferred = $true
        } elseif ($null -ne $Receipt) {
            throw "initial-sync-failed:$($Receipt.error)"
        } else {
            throw "initial-sync-failed"
        }
        if (-not $ProvisioningDeferred) {
            Invoke-Checked @(
                "run", "g2b-compare", "--home", $HomePath, "sync", "attributes",
                "--max-batches", "100"
            ) "attribute-sync-failed"
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
    }

    if (-not $ProvisioningDeferred) {
        Invoke-Checked @(
            "run", "g2b-compare", "--home", $HomePath, "verify"
        ) "verification-failed"
    }
    Invoke-Checked @(
        "run", "g2b-compare", "--home", $HomePath,
        "verify-secrets", "--all-storage"
    ) "secret-verification-failed"
    if ($ProvisionOnly) { exit 0 }

    $Server = Start-Process -FilePath "uv" -WindowStyle Hidden -PassThru -ArgumentList @(
        "run", "g2b-compare", "--home", $HomePath, "serve",
        "--host", $BindAddress, "--port", "$Port"
    )
    try {
        $HttpLive = $false
        foreach ($Attempt in 1..50) {
            if ($Server.HasExited) { throw "server-stopped-before-ready" }
            try {
                Invoke-RestMethod "http://${LoopbackAddress}:${Port}/livez" | Out-Null
                $HttpLive = $true
                break
            } catch [System.Net.Http.HttpRequestException] {
                Start-Sleep -Milliseconds 100
            } catch [System.Net.WebException] {
                Start-Sleep -Milliseconds 100
            }
        }
        if (-not $HttpLive) { throw "server-start-timeout" }
        Write-Host "server-ready:http://${LoopbackAddress}:${Port}/"
        Write-Host "lan-url:http://$($env:COMPUTERNAME):${Port}/"
        if (-not $NoBrowser) {
            & $BrowserLauncher "http://${LoopbackAddress}:${Port}/"
        }
        Wait-Process -Id $Server.Id
    } finally {
        if (-not $Server.HasExited) { Stop-Process -Id $Server.Id }
    }
} catch [System.Management.Automation.PipelineStoppedException] {
    exit 130
}
