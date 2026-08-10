param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $TauriArguments
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression
# powershell.exe -File consumes --debug as its own common parameter.
if ($DebugPreference -eq "Inquire") {
    $TauriArguments += "--debug"
}

$seedPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\src-tauri\resources\seed.sqlite3"))
$seedArchivePath = "$seedPath.zip"
$seedHashPath = "$seedArchivePath.sha256"

function Open-SharedReadStream {
    param([Parameter(Mandatory = $true)][string] $Path)

    $sharing = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
    return [IO.FileStream]::new(
        $Path,
        [IO.FileMode]::Open,
        [IO.FileAccess]::Read,
        $sharing
    )
}

function Get-SharedFileSha256 {
    param([Parameter(Mandatory = $true)][string] $Path)

    $stream = Open-SharedReadStream -Path $Path
    try {
        return (Get-StreamSha256 -Stream $stream).Hash
    }
    finally {
        $stream.Dispose()
    }
}

function Get-StreamSha256 {
    param(
        [Parameter(Mandatory = $true)][IO.Stream] $Stream,
        [long] $MaximumLength = [long]::MaxValue
    )

    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $buffer = New-Object byte[] (1024 * 1024)
        $length = 0L
        while (($read = $Stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            if ($length -gt ($MaximumLength - $read)) {
                throw "Seed archive entry exceeds its expected uncompressed length."
            }
            $length += $read
            $null = $hasher.TransformBlock($buffer, 0, $read, $buffer, 0)
        }
        $null = $hasher.TransformFinalBlock([byte[]]::new(0), 0, 0)
        return [pscustomobject]@{
            Hash = ([BitConverter]::ToString($hasher.Hash)).Replace("-", "").ToLowerInvariant()
            Length = $length
        }
    }
    finally {
        $hasher.Dispose()
    }
}

function Test-SeedArchive {
    param(
        [Parameter(Mandatory = $true)][string] $ArchivePath,
        [Parameter(Mandatory = $true)][string] $HashPath,
        [Parameter(Mandatory = $true)][string] $SourceHash,
        [Parameter(Mandatory = $true)][long] $SourceLength
    )

    if (-not ([IO.File]::Exists($ArchivePath) -and [IO.File]::Exists($HashPath))) {
        return $false
    }

    $stream = $null
    $archive = $null
    $entryStream = $null
    try {
        $recordedHash = [IO.File]::ReadAllText($HashPath).Trim()
        if ($recordedHash -cne $SourceHash) {
            return $false
        }

        $stream = Open-SharedReadStream -Path $ArchivePath
        $archive = [IO.Compression.ZipArchive]::new(
            $stream,
            [IO.Compression.ZipArchiveMode]::Read,
            $true
        )
        if ($archive.Entries.Count -ne 1) {
            return $false
        }

        $entry = $archive.Entries[0]
        if ($entry.FullName -cne "seed.sqlite3" -or $entry.Length -ne $SourceLength) {
            return $false
        }

        $entryStream = $entry.Open()
        $entryDigest = Get-StreamSha256 -Stream $entryStream -MaximumLength $SourceLength
        return $entryDigest.Length -eq $SourceLength `
            -and $entryDigest.Hash -ceq $SourceHash `
            -and $entryDigest.Hash -ceq $recordedHash
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $entryStream) {
            $entryStream.Dispose()
        }
        if ($null -ne $archive) {
            $archive.Dispose()
        }
        if ($null -ne $stream) {
            $stream.Dispose()
        }
    }
}

function Write-SeedArchive {
    param(
        [Parameter(Mandatory = $true)][string] $SourcePath,
        [Parameter(Mandatory = $true)][string] $TemporaryPath
    )

    $input = Open-SharedReadStream -Path $SourcePath
    $output = [IO.FileStream]::new(
        $TemporaryPath,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
    $hasher = [Security.Cryptography.SHA256]::Create()
    $archive = $null
    $entryStream = $null
    try {
        $archive = [IO.Compression.ZipArchive]::new(
            $output,
            [IO.Compression.ZipArchiveMode]::Create,
            $true
        )
        $entry = $archive.CreateEntry(
            "seed.sqlite3",
            [IO.Compression.CompressionLevel]::Optimal
        )
        $entry.LastWriteTime = [DateTimeOffset]::new(1980, 1, 1, 0, 0, 0, [TimeSpan]::Zero)
        $entryStream = $entry.Open()
        $buffer = New-Object byte[] (1024 * 1024)
        while (($read = $input.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $null = $hasher.TransformBlock($buffer, 0, $read, $buffer, 0)
            $entryStream.Write($buffer, 0, $read)
        }
        $null = $hasher.TransformFinalBlock([byte[]]::new(0), 0, 0)
        $entryStream.Dispose()
        $entryStream = $null
        $archive.Dispose()
        $archive = $null
        $output.Flush($true)
        return ([BitConverter]::ToString($hasher.Hash)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        if ($null -ne $entryStream) {
            $entryStream.Dispose()
        }
        if ($null -ne $archive) {
            $archive.Dispose()
        }
        $hasher.Dispose()
        $output.Dispose()
        $input.Dispose()
    }
}

function Publish-Atomically {
    param(
        [Parameter(Mandatory = $true)][string] $TemporaryPath,
        [Parameter(Mandatory = $true)][string] $DestinationPath
    )

    if ([IO.File]::Exists($DestinationPath)) {
        [IO.File]::Replace($TemporaryPath, $DestinationPath, $null)
    }
    else {
        [IO.File]::Move($TemporaryPath, $DestinationPath)
    }
}

function Ensure-SeedArchive {
    if (-not [IO.File]::Exists($seedPath)) {
        throw "Seed database was not found. Run prepare-seed.ps1 before packaging."
    }

    $sourceHash = Get-SharedFileSha256 -Path $seedPath
    $sourceLength = [IO.FileInfo]::new($seedPath).Length
    if (Test-SeedArchive -ArchivePath $seedArchivePath -HashPath $seedHashPath -SourceHash $sourceHash -SourceLength $sourceLength) {
        return
    }

    $temporaryArchive = "$seedArchivePath.temporary"
    $temporaryHash = "$seedHashPath.temporary"
    Remove-Item -LiteralPath $temporaryArchive -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $temporaryHash -Force -ErrorAction SilentlyContinue
    try {
        $archivedHash = Write-SeedArchive -SourcePath $seedPath -TemporaryPath $temporaryArchive
        $currentHash = Get-SharedFileSha256 -Path $seedPath
        if ($archivedHash -cne $sourceHash -or $currentHash -cne $sourceHash) {
            throw "Seed database changed while the package archive was generated."
        }

        Publish-Atomically -TemporaryPath $temporaryArchive -DestinationPath $seedArchivePath
        [IO.File]::WriteAllText(
            $temporaryHash,
            "$sourceHash`n",
            [Text.UTF8Encoding]::new($false)
        )
        Publish-Atomically -TemporaryPath $temporaryHash -DestinationPath $seedHashPath
    }
    finally {
        Remove-Item -LiteralPath $temporaryArchive -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $temporaryHash -Force -ErrorAction SilentlyContinue
    }
}

Ensure-SeedArchive

$targetRoot = Join-Path $env:LOCALAPPDATA "G2BCompareDesktop\cargo-target"
$tauri = Join-Path $PSScriptRoot "..\node_modules\.bin\tauri.cmd"

$env:CARGO_TARGET_DIR = $targetRoot
$env:CARGO_INCREMENTAL = "0"
& $tauri @TauriArguments
exit $LASTEXITCODE
