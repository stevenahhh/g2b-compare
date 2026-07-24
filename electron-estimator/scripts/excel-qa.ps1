[CmdletBinding()]
param(
    [string]$InputDir,
    [Alias("Input")]
    [string]$InputPath,
    [Parameter(Mandatory = $true)]
    [string]$OutDir,
    [switch]$Worker,
    [string]$ReceiptPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$datasetRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "..\dataset"))
$outputRoot = [IO.Path]::GetFullPath($OutDir)

function Test-UnderPath {
    param([string]$Candidate, [string]$Parent)
    $candidatePath = [IO.Path]::GetFullPath($Candidate).TrimEnd("\")
    $parentPath = [IO.Path]::GetFullPath($Parent).TrimEnd("\")
    return $candidatePath -eq $parentPath -or
        $candidatePath.StartsWith(
            "$parentPath\",
            [StringComparison]::OrdinalIgnoreCase
        )
}

function Get-Sha256 {
    param([string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-RepairLogs {
    param([string]$Directory)
    $locations = @(
        $Directory,
        $env:TEMP,
        (Join-Path $env:LOCALAPPDATA "Microsoft\Office\UnsavedFiles")
    )
    return @(
        foreach ($location in $locations) {
            if (Test-Path -LiteralPath $location) {
                Get-ChildItem -LiteralPath $location -File -ErrorAction SilentlyContinue |
                    Where-Object {
                        $_.Name -match "^(error|recovery|repaired).*[.](xml|log)$"
                    } |
                    ForEach-Object { $_.FullName }
            }
        }
    ) | Sort-Object -Unique
}

function Write-Stage {
    param([string]$Profile, [string]$Stage)
    Write-Host (
        "TASK15_EXCEL_STAGE {0:o} {1} {2}" -f
        [DateTime]::UtcNow,
        $Profile,
        $Stage
    )
}

function Get-Profile {
    param([string]$Name)
    $materialSheet = -join @(
        [char]0xC790,
        [char]0xC7AC,
        [char]0xB0B4,
        [char]0xC5ED,
        [char]0xC11C
    )
    $procurementSheet = -join @(
        [char]0xAD00,
        [char]0xAE09,
        [char]0xB0B4,
        [char]0xC5ED,
        [char]0xC11C
    )
    $summarySheet = -join @([char]0xC694, [char]0xC57D)
    if ($Name.StartsWith("A-")) {
        return @{
            Id = "A"
            Sheet = $materialSheet
            Range = "B1:N31"
            MaxPages = 20
        }
    }
    if ($Name.StartsWith("B-")) {
        return @{
            Id = "B"
            Sheet = $procurementSheet
            Range = "A1:V21"
            MaxPages = 40
        }
    }
    if ($Name.StartsWith("C-")) {
        return @{
            Id = "C"
            Sheet = $procurementSheet
            Range = "A1:V37"
            MaxPages = 50
        }
    }
    if ($Name.StartsWith("native-")) {
        return @{
            Id = "native"
            Sheet = $summarySheet
            Range = "A1:E204"
            MaxPages = 20
        }
    }
    throw "EXCEL_QA_PROFILE_UNKNOWN:$Name"
}

function Get-FormulaErrors {
    param($Worksheet, [string]$Address)
    $errors = [Collections.Generic.List[string]]::new()
    $range = $null
    try {
        $range = $Worksheet.Range($Address)
        $rowCount = [int]$range.Rows.Count
        $columnCount = [int]$range.Columns.Count
        for ($row = 1; $row -le $rowCount; $row++) {
            for ($column = 1; $column -le $columnCount; $column++) {
                $cell = $null
                try {
                    $cell = $range.Cells.Item($row, $column)
                    if ([bool]$cell.HasFormula) {
                        $text = [string]$cell.Text
                        if ($text -match "#(REF!|VALUE!|NAME\?|DIV/0!)") {
                            $coordinate = [string]$cell.Address($false, $false)
                            $errors.Add("$($Worksheet.Name)!$coordinate=$text")
                        }
                    }
                }
                finally {
                    if ($null -ne $cell) {
                        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($cell)
                    }
                }
            }
        }
    }
    finally {
        if ($null -ne $range) {
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($range)
        }
    }
    return @($errors | Sort-Object -Unique)
}

function Open-Workbook {
    param($Excel, [string]$Path, [bool]$ReadOnly)
    return $Excel.Workbooks.Open($Path, 0, $ReadOnly)
}

function Get-PdfPages {
    param([string]$Path)
    $bytes = [IO.File]::ReadAllBytes($Path)
    $text = [Text.Encoding]::ASCII.GetString($bytes)
    $pageCount = [regex]::Matches(
        $text,
        "/Type\s*/Page(?!s)\b"
    ).Count
    if ($pageCount -lt 1) {
        throw "EXCEL_QA_PDFINFO_FAILED:$Path"
    }
    return $pageCount
}

if ([string]::IsNullOrWhiteSpace($InputDir) -eq
    [string]::IsNullOrWhiteSpace($InputPath)) {
    throw "EXCEL_QA_USE_EXACTLY_ONE_INPUT"
}

if (-not [string]::IsNullOrWhiteSpace($InputPath)) {
    $guardInput = if ($InputPath -match "[*?]") {
        Split-Path -Parent $InputPath
    }
    else {
        $InputPath
    }
    $literalInput = [IO.Path]::GetFullPath($guardInput)
    if (Test-UnderPath $literalInput $datasetRoot) {
        throw "QA_SOURCE_PATH_FORBIDDEN"
    }
    $inputFiles = @(Get-Item -Path $InputPath | Where-Object {
        -not $_.PSIsContainer -and $_.Extension -eq ".xlsx"
    })
}
else {
    $resolvedInputDir = [IO.Path]::GetFullPath($InputDir)
    if (Test-UnderPath $resolvedInputDir $datasetRoot) {
        throw "QA_SOURCE_PATH_FORBIDDEN"
    }
    if ($resolvedInputDir -eq $outputRoot) {
        throw "EXCEL_QA_COPY_DIRECTORY_REQUIRED"
    }
    $inputFiles = @(Get-ChildItem -LiteralPath $resolvedInputDir -File |
        Where-Object { $_.Extension -eq ".xlsx" } |
        Sort-Object Name)
}

$expectedCount = if ($Worker) { 1 } else { 4 }
if ($inputFiles.Count -ne $expectedCount) {
    throw "EXCEL_QA_EXPECTED_$($expectedCount):$($inputFiles.Count)"
}
if (Test-UnderPath $outputRoot $datasetRoot) {
    throw "QA_SOURCE_PATH_FORBIDDEN"
}

[void](New-Item -ItemType Directory -Force $outputRoot)
$inputHashesBefore = @{}
foreach ($inputFile in $inputFiles) {
    $inputHashesBefore[$inputFile.FullName] = Get-Sha256 $inputFile.FullName
}

if (-not $Worker -and -not [string]::IsNullOrWhiteSpace($InputDir)) {
    $workerRoot = Join-Path $outputRoot ".worker-receipts"
    [void](New-Item -ItemType Directory -Force $workerRoot)
    $workerReceipts = [Collections.Generic.List[string]]::new()
    for ($index = 0; $index -lt $inputFiles.Count; $index += 2) {
        $jobs = [Collections.Generic.List[object]]::new()
        foreach ($offset in 0, 1) {
            $fileIndex = $index + $offset
            if ($fileIndex -ge $inputFiles.Count) {
                continue
            }
            $file = $inputFiles[$fileIndex]
            $workerReceipt = Join-Path $workerRoot "$($file.BaseName).json"
            $workerReceipts.Add($workerReceipt)
            $jobs.Add((Start-Job -ScriptBlock {
                param(
                    [string]$ScriptPath,
                    [string]$FilePath,
                    [string]$WorkerOutput,
                    [string]$WorkerReceipt
                )
                & powershell.exe -NoProfile -ExecutionPolicy Bypass `
                    -File $ScriptPath `
                    -InputPath $FilePath `
                    -OutDir $WorkerOutput `
                    -Worker `
                    -ReceiptPath $WorkerReceipt
                [pscustomobject]@{ ExitCode = $LASTEXITCODE }
            } -ArgumentList @(
                $PSCommandPath,
                $file.FullName,
                $outputRoot,
                $workerReceipt
            )))
        }
        $jobs | Wait-Job | Out-Null
        foreach ($job in $jobs) {
            $jobOutput = @(Receive-Job $job)
            $exitRecord = $jobOutput | Where-Object {
                $_.PSObject.Properties.Name -contains "ExitCode"
            } | Select-Object -Last 1
            $jobOutput | Where-Object {
                $_.PSObject.Properties.Name -notcontains "ExitCode"
            } | ForEach-Object { Write-Host $_ }
            if (
                $job.State -ne "Completed" -or
                $null -eq $exitRecord -or
                $exitRecord.ExitCode -ne 0
            ) {
                throw "EXCEL_QA_WORKER_FAILED:$($job.Id)"
            }
            Remove-Job $job
        }
    }

    $workerVersions = [Collections.Generic.List[string]]::new()
    $workerResults = @(
        foreach ($workerReceipt in $workerReceipts) {
            $workerData = Get-Content -Raw -Encoding UTF8 `
                -LiteralPath $workerReceipt |
                ConvertFrom-Json
            $workerVersions.Add([string]$workerData.excelVersion)
            $workerData.workbooks
        }
    ) | Sort-Object profile
    $inputHashesAfter = @{}
    foreach ($inputFile in $inputFiles) {
        $inputHashesAfter[$inputFile.FullName] = Get-Sha256 $inputFile.FullName
        if ($inputHashesAfter[$inputFile.FullName] -ne
            $inputHashesBefore[$inputFile.FullName]) {
            throw "EXCEL_QA_INPUT_CHANGED:$($inputFile.Name)"
        }
    }
    $sourceReceipts = @()
    $prepareReceiptPath = Join-Path (
        [IO.Path]::GetFullPath($InputDir)
    ) "task-15-prepare-receipt.json"
    if (-not (Test-Path -LiteralPath $prepareReceiptPath)) {
        throw "EXCEL_QA_PREPARE_RECEIPT_MISSING"
    }
    $prepareReceipt = Get-Content -Raw -Encoding UTF8 `
        -LiteralPath $prepareReceiptPath |
        ConvertFrom-Json
    $sourceReceipts = @(
        foreach ($legacy in $prepareReceipt.legacy) {
            $sourceShaAfterExcel = Get-Sha256 $legacy.sourcePath
            if ($sourceShaAfterExcel -ne $legacy.sourceSha256Before) {
                throw "EXCEL_QA_SOURCE_CHANGED:$($legacy.id)"
            }
            [ordered]@{
                profile = $legacy.id
                sourcePath = $legacy.sourcePath
                sourceSha256Before = $legacy.sourceSha256Before
                sourceSha256After = $sourceShaAfterExcel
            }
        }
    )
    $excelVersions = @($workerVersions | Sort-Object -Unique)
    $receipt = [ordered]@{
        schemaVersion = "task-15-excel-qa-v1"
        status = "pass"
        excelVersions = $excelVersions
        copyOnly = $true
        workbookCount = $workerResults.Count
        workbooks = $workerResults
        inputsUnchanged = $true
        sourcesUnchanged = $true
        sourceReceipts = $sourceReceipts
    }
    $finalReceiptPath = Join-Path (
        Split-Path $outputRoot -Parent
    ) "task-15-excel-qa.json"
    $receiptJson = $receipt | ConvertTo-Json -Depth 10
    [IO.File]::WriteAllText(
        $finalReceiptPath,
        $receiptJson,
        [Text.UTF8Encoding]::new($false)
    )
    $receiptJson
    return
}

$excel = $null
$results = [Collections.Generic.List[object]]::new()
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
    $excel.EnableEvents = $false
    $excel.AutomationSecurity = 3
    $excelVersion = [string]$excel.Version

    foreach ($inputFile in $inputFiles) {
        $profile = Get-Profile $inputFile.Name
        $copyPath = Join-Path $outputRoot $inputFile.Name
        $pdfPath = Join-Path $outputRoot "$($profile.Id)-$($profile.Sheet).pdf"
        Copy-Item -LiteralPath $inputFile.FullName -Destination $copyPath -Force
        $copyShaBefore = Get-Sha256 $copyPath
        $workbook = $null
        $worksheet = $null
        $before = @()
        $repairLogsBefore = @(Get-RepairLogs $outputRoot)
        try {
            Write-Stage $profile.Id "open-start"
            $workbook = Open-Workbook $excel $copyPath $false
            Write-Stage $profile.Id "open-complete"
            $worksheet = $workbook.Worksheets.Item($profile.Sheet)
            Write-Stage $profile.Id "scan-before-start"
            $before = @(Get-FormulaErrors $worksheet $profile.Range)
            Write-Stage $profile.Id "scan-before-complete"
            Write-Stage $profile.Id "calculate-start"
            $excel.CalculateFullRebuild()
            Write-Stage $profile.Id "calculate-complete"
            $workbook.Save()
            Write-Stage $profile.Id "save-complete"
            $worksheet.ExportAsFixedFormat(0, $pdfPath, 0, $true, $false)
            Write-Stage $profile.Id "pdf-complete"
            $workbook.Close($true)
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($worksheet)
            $worksheet = $null
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($workbook)
            $workbook = $null

            $workbook = Open-Workbook $excel $copyPath $true
            $worksheet = $workbook.Worksheets.Item($profile.Sheet)
            Write-Stage $profile.Id "reopen-complete"
            $after = @(Get-FormulaErrors $worksheet $profile.Range)
            Write-Stage $profile.Id "scan-after-complete"
            $workbook.Close($false)
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($worksheet)
            $worksheet = $null
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($workbook)
            $workbook = $null

            $newErrors = @($after | Where-Object { $_ -notin $before })
            $repairLogsAfter = @(Get-RepairLogs $outputRoot)
            $newRepairLogs = @(
                $repairLogsAfter | Where-Object { $_ -notin $repairLogsBefore }
            )
            $pageCount = Get-PdfPages $pdfPath
            if ($newErrors.Count -ne 0) {
                throw "EXCEL_QA_NEW_FORMULA_ERRORS:$($profile.Id)"
            }
            if ($pageCount -lt 1 -or $pageCount -gt $profile.MaxPages) {
                throw "EXCEL_QA_PAGE_COUNT:$($profile.Id):$pageCount"
            }
            if ($newRepairLogs.Count -ne 0) {
                throw "EXCEL_QA_REPAIR_LOG:$($profile.Id)"
            }
            $results.Add([ordered]@{
                status = "pass"
                profile = $profile.Id
                inputPath = $inputFile.FullName
                inputSha256Before = $inputHashesBefore[$inputFile.FullName]
                copyPath = $copyPath
                copySha256Before = $copyShaBefore
                copySha256After = Get-Sha256 $copyPath
                worksheet = $profile.Sheet
                activeRange = $profile.Range
                formulaErrorsBefore = $before
                formulaErrorsAfter = $after
                newFormulaErrors = $newErrors
                newFormulaErrorCount = $newErrors.Count
                repairDialogDetected = ($newRepairLogs.Count -ne 0)
                repairLogPaths = $newRepairLogs
                reopened = $true
                pdfPath = $pdfPath
                pdfPageCount = $pageCount
            })
        }
        finally {
            if ($null -ne $worksheet) {
                [void][Runtime.InteropServices.Marshal]::ReleaseComObject($worksheet)
            }
            if ($null -ne $workbook) {
                $workbook.Close($false)
                [void][Runtime.InteropServices.Marshal]::ReleaseComObject($workbook)
            }
        }
    }
}
finally {
    if ($null -ne $excel) {
        $excel.Quit()
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

$inputHashesAfter = @{}
foreach ($inputFile in $inputFiles) {
    $inputHashesAfter[$inputFile.FullName] = Get-Sha256 $inputFile.FullName
    if ($inputHashesAfter[$inputFile.FullName] -ne
        $inputHashesBefore[$inputFile.FullName]) {
        throw "EXCEL_QA_INPUT_CHANGED:$($inputFile.Name)"
    }
}

$receipt = [ordered]@{
    schemaVersion = "task-15-excel-qa-v1"
    status = "pass"
    excelVersion = $excelVersion
    copyOnly = $true
    workbookCount = $results.Count
    workbooks = @($results)
    inputsUnchanged = $true
}
$actualReceiptPath = if ([string]::IsNullOrWhiteSpace($ReceiptPath)) {
    Join-Path (Split-Path $outputRoot -Parent) "task-15-excel-qa.json"
}
else {
    [IO.Path]::GetFullPath($ReceiptPath)
}
$receiptJson = $receipt | ConvertTo-Json -Depth 10
[IO.File]::WriteAllText(
    $actualReceiptPath,
    $receiptJson,
    [Text.UTF8Encoding]::new($false)
)
$receiptJson
