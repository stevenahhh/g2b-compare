[CmdletBinding()]
param(
    [switch]$Help,
    [switch]$NoBrowser,
    [switch]$CheckOnly,
    [switch]$SkipUpdate,
    [string]$UpdateSource = "https://github.com/stevenahhh/g2b-compare"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$AppUrl = "http://127.0.0.1:8765/"
$LocalVersionPath = Join-Path $ProjectRoot "APP_VERSION.txt"

function Write-Step {
    param(
        [int]$Number,
        [int]$Total,
        [string]$Message
    )
    Write-Host "[$Number/$Total] $Message" -ForegroundColor Cyan
}

function Write-Failure {
    param(
        [string]$Title,
        [string[]]$Actions
    )
    Write-Host ""
    Write-Host "[ERROR] $Title" -ForegroundColor Red
    foreach ($Action in $Actions) {
        Write-Host "  - $Action" -ForegroundColor Yellow
    }
}

function Resolve-Python {
    $Python = Get-Command python -ErrorAction SilentlyContinue
    if ($Python) {
        return [pscustomobject]@{
            Command = $Python.Source
            Prefix = @()
        }
    }
    $Launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($Launcher) {
        return [pscustomobject]@{
            Command = $Launcher.Source
            Prefix = @("-3.12")
        }
    }
    return $null
}

function Install-Python {
    Write-Host "  Python is not installed. Installing Python 3.12..." (
        -ForegroundColor Cyan
    )
    $Winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($Winget) {
        & $Winget.Source install --id Python.Python.3.12 --exact `
            --scope user --silent --accept-package-agreements `
            --accept-source-agreements --disable-interactivity
        if ($LASTEXITCODE -eq 0) {
            $env:Path = (
                "$env:LOCALAPPDATA\Programs\Python\Python312;" +
                "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts;" +
                $env:Path
            )
            $Installed = Resolve-Python
            if ($Installed) {
                return $Installed
            }
        }
    }

    $InstallerUrl = (
        "https://www.python.org/ftp/python/3.12.10/" +
        "python-3.12.10-amd64.exe"
    )
    $InstallerPath = Join-Path $env:TEMP "python-3.12.10-amd64.exe"
    try {
        [Net.ServicePointManager]::SecurityProtocol = (
            [Net.SecurityProtocolType]::Tls12
        )
        Invoke-WebRequest -Uri $InstallerUrl -OutFile $InstallerPath -TimeoutSec 120
        $Process = Start-Process -FilePath $InstallerPath -ArgumentList @(
            "/quiet",
            "InstallAllUsers=0",
            "PrependPath=1",
            "Include_test=0",
            "Include_launcher=1",
            "InstallLauncherAllUsers=0"
        ) -Wait -PassThru
        if ($Process.ExitCode -eq 0) {
            $env:Path = (
                "$env:LOCALAPPDATA\Programs\Python\Python312;" +
                "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts;" +
                $env:Path
            )
            return Resolve-Python
        }
    } catch {
        return $null
    } finally {
        Remove-Item -LiteralPath $InstallerPath -Force -ErrorAction SilentlyContinue
    }
    return $null
}

function Resolve-Uv {
    $Uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($Uv) {
        return $Uv.Source
    }
    $Python = Resolve-Python
    if (-not $Python) {
        return $null
    }
    $ScriptsPath = & $Python.Command @($Python.Prefix) -c (
        "import sysconfig; print(sysconfig.get_path('scripts'))"
    )
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    $Candidate = Join-Path (($ScriptsPath | Select-Object -Last 1).Trim()) "uv.exe"
    if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
        return $Candidate
    }
    return $null
}

function Convert-AppVersion {
    param([string]$Value)
    try {
        return [version]$Value.Trim()
    } catch {
        return $null
    }
}

function Copy-UpdateContent {
    param([string]$SourceRoot)

    foreach ($RelativePath in @(
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        ".env.example",
        "README.md",
        "scripts",
        "src"
    )) {
        $Source = Join-Path $SourceRoot $RelativePath
        if (-not (Test-Path -LiteralPath $Source)) {
            continue
        }
        $Destination = Join-Path $ProjectRoot $RelativePath
        if (Test-Path -LiteralPath $Source -PathType Container) {
            if (Test-Path -LiteralPath $Destination) {
                Remove-Item -LiteralPath $Destination -Recurse -Force
            }
            New-Item -ItemType Directory -Path (
                Split-Path -Parent $Destination
            ) -Force | Out-Null
            Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
        } else {
            New-Item -ItemType Directory -Path (
                Split-Path -Parent $Destination
            ) -Force | Out-Null
            Copy-Item -LiteralPath $Source -Destination $Destination -Force
        }
    }
}

function Invoke-SourceUpdate {
    if ($SkipUpdate -or -not (Test-Path -LiteralPath $LocalVersionPath)) {
        return
    }

    $TemporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
        "g2b-update-" + [guid]::NewGuid().ToString("N")
    )
    try {
        $LocalText = (Get-Content -LiteralPath $LocalVersionPath -Raw).Trim()
        $LocalVersion = Convert-AppVersion $LocalText
        if ($null -eq $LocalVersion) {
            Write-Host "  Update skipped: invalid local version." -ForegroundColor Yellow
            return
        }

        New-Item -ItemType Directory -Path $TemporaryRoot -Force | Out-Null
        $ArchivePath = Join-Path $TemporaryRoot "source.zip"
        $ExtractPath = Join-Path $TemporaryRoot "extract"

        if (Test-Path -LiteralPath $UpdateSource -PathType Container) {
            $RemoteVersionPath = Join-Path $UpdateSource "APP_VERSION.txt"
            $RemoteArchivePath = Join-Path $UpdateSource "source.zip"
            if (
                -not (Test-Path -LiteralPath $RemoteVersionPath) -or
                -not (Test-Path -LiteralPath $RemoteArchivePath)
            ) {
                Write-Host (
                    "  Update check unavailable. Starting installed version."
                ) -ForegroundColor DarkGray
                Write-Output "update-result:offline"
                return
            }
            $RemoteText = (
                Get-Content -LiteralPath $RemoteVersionPath -Raw
            ).Trim()
            Copy-Item -LiteralPath $RemoteArchivePath -Destination $ArchivePath
        } else {
            [Net.ServicePointManager]::SecurityProtocol = (
                [Net.SecurityProtocolType]::Tls12
            )
            $RemoteText = (
                Invoke-RestMethod -Uri (
                    "$UpdateSource/raw/refs/heads/main/APP_VERSION.txt"
                ) -TimeoutSec 8
            ).ToString().Trim()
            Invoke-WebRequest -Uri (
                "$UpdateSource/archive/refs/heads/main.zip"
            ) -OutFile $ArchivePath -TimeoutSec 30
        }

        $RemoteVersion = Convert-AppVersion $RemoteText
        if ($null -eq $RemoteVersion -or $RemoteVersion -le $LocalVersion) {
            Write-Host (
                "  Installed version is current ($LocalText)."
            ) -ForegroundColor DarkGray
            Write-Output (
                "update-result:skipped:current=$LocalText,remote=$RemoteText"
            )
            return
        }

        Write-Host "  Updating $LocalText -> $RemoteText..." -ForegroundColor Cyan
        Expand-Archive -LiteralPath $ArchivePath -DestinationPath $ExtractPath -Force
        $ArchiveRoot = Get-ChildItem -LiteralPath $ExtractPath -Directory |
            Select-Object -First 1
        if ($null -eq $ArchiveRoot) {
            throw "invalid-update-archive"
        }
        foreach ($RequiredPath in @(
            "APP_VERSION.txt",
            "pyproject.toml",
            "uv.lock",
            "scripts\start.py",
            "src\g2b_compare\web\frontend_dist\index.html"
        )) {
            if (
                -not (
                    Test-Path -LiteralPath (
                        Join-Path $ArchiveRoot.FullName $RequiredPath
                    ) -PathType Leaf
                )
            ) {
                throw "incomplete-update-archive"
            }
        }
        $StagedVersion = (
            Get-Content -LiteralPath (
                Join-Path $ArchiveRoot.FullName "APP_VERSION.txt"
            ) -Raw
        ).Trim()
        if ($StagedVersion -cne $RemoteText) {
            throw "update-version-mismatch"
        }

        Copy-UpdateContent -SourceRoot $ArchiveRoot.FullName
        Set-Content -LiteralPath $LocalVersionPath -Value $RemoteText -Encoding Ascii
        Write-Host (
            "  Update complete. User settings and data were preserved."
        ) -ForegroundColor Green
        Write-Output "update-result:applied:$RemoteText"
    } catch {
        Write-Host (
            "  Update check failed. Starting installed version."
        ) -ForegroundColor Yellow
        Write-Output "update-result:offline"
    } finally {
        if (Test-Path -LiteralPath $TemporaryRoot) {
            Remove-Item -LiteralPath $TemporaryRoot -Recurse -Force `
                -ErrorAction SilentlyContinue
        }
    }
}

if ($Help) {
    Write-Output @"
G2B Compare quick start

1. Double-click START_APP.bat.
2. The first run prepares Python packages automatically.
3. The browser opens at $AppUrl.
4. Keep the terminal window open while using the app.
5. Press Ctrl+C in the terminal to stop the app.

Service key:
  The handoff ZIP already includes the configured .env file.
  GitHub updates preserve .env and .g2b.
"@
    exit 0
}

Set-Location $ProjectRoot
Write-Host ""
Write-Host "G2B Compare" -ForegroundColor White
Write-Host "One-click local web application" -ForegroundColor DarkGray
Write-Host ""

Write-Step 1 5 "Checking for updates..."
Invoke-SourceUpdate

Write-Step 2 5 "Checking Windows and required files..."
if (-not $IsWindows -and $PSVersionTable.PSEdition -ne "Desktop") {
    Write-Failure "This launcher supports Windows only." @(
        "Run it on Windows 10 or Windows 11."
    )
    exit 1
}
foreach ($RequiredPath in @(
    "pyproject.toml",
    "uv.lock",
    "scripts\start.py",
    "src\g2b_compare\web\frontend_dist\index.html"
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        Write-Failure "The package is incomplete: $RequiredPath is missing." @(
            "Extract the ZIP again into a normal writable folder.",
            "Do not run the app from inside the ZIP preview."
        )
        exit 1
    }
}

if ($CheckOnly) {
    Write-Host ""
    Write-Host "Package and update check passed." -ForegroundColor Green
    exit 0
}

Write-Step 3 5 "Checking the Python runtime..."
$Python = Resolve-Python
if (-not $Python) {
    $Python = Install-Python
    if (-not $Python) {
        Write-Failure "Python automatic installation failed." @(
            "Check your internet connection and Windows installation permissions.",
            "Install Python 3.12 from https://www.python.org/downloads/ if needed.",
            "Then double-click START_APP.bat again."
        )
        exit 1
    }
}

$Version = & $Python.Command @($Python.Prefix) -c (
    "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
)
if ($LASTEXITCODE -ne 0 -or $Version.Trim() -notin @("3.12", "3.13")) {
    Write-Failure "Python $($Version.Trim()) is not supported." @(
        "Install Python 3.12 or 3.13.",
        "Then double-click START_APP.bat again."
    )
    exit 1
}

Write-Step 4 5 "Checking the package manager..."
$Uv = Resolve-Uv
if (-not $Uv) {
    Write-Host "  uv is not installed. Installing it now..." -ForegroundColor DarkGray
    & $Python.Command @($Python.Prefix) -m pip install --user uv
    if ($LASTEXITCODE -ne 0) {
        Write-Failure "uv installation failed." @(
            "Check your internet connection.",
            "Run: python -m pip install --user uv",
            "Then double-click START_APP.bat again."
        )
        exit 1
    }
    $Uv = Resolve-Uv
}
if (-not $Uv) {
    Write-Failure "uv was installed but could not be located." @(
        "Close this window and double-click START_APP.bat again."
    )
    exit 1
}

Write-Step 5 5 "Preparing and starting the application..."
Write-Host "  First run may take several minutes." -ForegroundColor DarkGray
Write-Host "  App address: $AppUrl" -ForegroundColor DarkGray
Write-Host "  Stop: press Ctrl+C in this window." -ForegroundColor DarkGray
Write-Host ""

$Arguments = @(
    "run",
    "python",
    ".\scripts\start.py",
    "--home",
    ".g2b"
)
if ($NoBrowser) {
    $Arguments += "--no-browser"
}
& $Uv @Arguments
$ExitCode = $LASTEXITCODE
if ($ExitCode -eq 130) {
    Write-Host ""
    Write-Host "Application stopped." -ForegroundColor Green
    exit 0
}
if ($ExitCode -ne 0) {
    Write-Failure "The application stopped with error code $ExitCode." @(
        "Check whether another program is using port 8765.",
        "Check whether antivirus software blocked Python.",
        "Open QUICK_START.txt for troubleshooting."
    )
}
exit $ExitCode
