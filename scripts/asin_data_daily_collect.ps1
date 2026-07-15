param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath,

    [string]$RunId = ("asin-data-daily-" + (Get-Date -Format "yyyyMMdd-HHmmss")),
    [string]$OutputDir = "output/asin-data",
    [string]$Site = "US",
    [string]$SalesStart = "",
    [string]$SalesEnd = "",
    [switch]$DryRun,
    [switch]$NoUpload
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot
$env:PYTHONPATH = "."

if (-not (Test-Path -LiteralPath $InputPath)) {
    throw "Input file not found: $InputPath. Please create a CSV/XLSX/JSON/JSONL file with at least an 'asin' column, or pass -InputPath to an existing file."
}
$resolvedInput = Resolve-Path -LiteralPath $InputPath
$runRoot = Join-Path $OutputDir $RunId
$logDir = Join-Path $runRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function New-StageJob {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Stage
    )

    Start-Job -Name $Stage -ScriptBlock {
        param($RepoRoot, $Stage, $InputPath, $RunId, $OutputDir, $Site, $SalesStart, $SalesEnd, $DryRun)

        Set-Location $RepoRoot
        $env:PYTHONPATH = "."
        $args = @(
            "-m", "opscli.cli",
            "asin-data", "stage-collect",
            "--stage", $Stage,
            "--input", $InputPath,
            "--site", $Site,
            "--run-id", $RunId,
            "--output-dir", $OutputDir,
            "--pretty"
        )
        if ($SalesStart) {
            $args += @("--sales-start", $SalesStart)
        }
        if ($SalesEnd) {
            $args += @("--sales-end", $SalesEnd)
        }
        if ($DryRun) {
            $args += "--dry-run"
        }

        & python @args
        if ($LASTEXITCODE -ne 0) {
            throw "asin-data stage failed: $Stage, exit_code=$LASTEXITCODE"
        }
    } -ArgumentList $repoRoot.Path, $Stage, $resolvedInput.Path, $RunId, $OutputDir, $Site, $SalesStart, $SalesEnd, $DryRun
}

function Wait-StageJobs {
    param(
        [Parameter(Mandatory = $true)]
        [array]$Jobs
    )

    Wait-Job -Job $Jobs | Out-Null
    $failed = @()
    foreach ($job in $Jobs) {
        $logPath = Join-Path $logDir ($job.Name + ".log")
        Receive-Job -Job $job -Keep | Tee-Object -FilePath $logPath | Out-Null
        if ($job.State -ne "Completed") {
            $failed += $job.Name
        }
        Remove-Job -Job $job -Force
    }
    if ($failed.Count -gt 0) {
        throw "Failed stages: $($failed -join ', '). Check logs under $logDir"
    }
}

Write-Host "RunId: $RunId"
Write-Host "Input: $($resolvedInput.Path)"
Write-Host "Output: $runRoot"

$wave1Stages = @(
    "rufus",
    "query",
    "bi",
    "basic",
    "seller-keyword-reverse",
    "seller-listing-analysis"
)

Write-Host "Starting wave 1 stages: $($wave1Stages -join ', ')"
$wave1Jobs = foreach ($stage in $wave1Stages) {
    New-StageJob -Stage $stage
}
Wait-StageJobs -Jobs $wave1Jobs

Write-Host "Starting wave 2 stage: seller-keyword-miner"
$minerJob = New-StageJob -Stage "seller-keyword-miner"
Wait-StageJobs -Jobs @($minerJob)

$mergeArgs = @(
    "-m", "opscli.cli",
    "asin-data", "merge-stages",
    "--input", $resolvedInput.Path,
    "--site", $Site,
    "--run-id", $RunId,
    "--output-dir", $OutputDir,
    "--pretty"
)
if ($NoUpload -or $DryRun) {
    $mergeArgs += "--no-upload"
}

Write-Host "Merging stages and building package"
& python @mergeArgs
if ($LASTEXITCODE -ne 0) {
    throw "asin-data merge-stages failed, exit_code=$LASTEXITCODE"
}

Write-Host "Done. Output: $runRoot"
