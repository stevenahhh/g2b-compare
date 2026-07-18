[CmdletBinding()]
param(
    [ValidateSet("full", "delta", "attributes")]
    [string]$Mode = "delta",
    [string]$HomePath = ".g2b"
)

$ErrorActionPreference = "Stop"
uv sync --frozen
if ($LASTEXITCODE -ne 0) { throw "dependency-sync-failed" }
try {
    uv run g2b-compare --home $HomePath sync $Mode
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} catch [System.Management.Automation.PipelineStoppedException] {
    exit 130
}
exit 0
