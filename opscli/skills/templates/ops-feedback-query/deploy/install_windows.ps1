param(
    [Parameter(Mandatory = $false)]
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..\..")),

    [Parameter(Mandatory = $false)]
    [string]$TaskName = "OpsCLI Feedback Daily Insight"
)

$ErrorActionPreference = "Stop"

$resolvedProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$pythonPath = Join-Path $resolvedProjectRoot ".venv\Scripts\python.exe"
$reportScript = Join-Path $resolvedProjectRoot "opscli\skills\templates\ops-feedback-query\scripts\daily_feedback_report.py"

foreach ($requiredPath in @($pythonPath, $reportScript)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required file does not exist: $requiredPath"
    }
}

$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument ('"' + $reportScript + '" --prepare-only') `
    -WorkingDirectory $resolvedProjectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours(8).AddMinutes(30))
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited
$definition = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Prepare yesterday feedback at 08:30 and write READY for Codex App insight"

Register-ScheduledTask -TaskName $TaskName -InputObject $definition -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
$taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName
[pscustomobject]@{
    task_name = $task.TaskName
    state = $task.State.ToString()
    next_run_time = $taskInfo.NextRunTime.ToString("yyyy-MM-dd HH:mm:ss")
    execute = $task.Actions[0].Execute
    arguments = $task.Actions[0].Arguments
    working_directory = $task.Actions[0].WorkingDirectory
} | ConvertTo-Json -Compress
