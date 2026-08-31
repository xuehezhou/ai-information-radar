# Register low-cost collection and daily finalization tasks.
# API keys are never embedded in task commands.

param(
    [string]$PythonExe = ''
)

$ErrorActionPreference = 'Stop'

$proj = Split-Path -Parent $PSScriptRoot
$collector = Join-Path $proj 'src\collector.py'
$generator = Join-Path $proj 'src\generate_daily.py'
$logDir = Join-Path $proj 'data\logs'
$collectLog = Join-Path $logDir 'collect.log'
$finalizeLog = Join-Path $logDir 'daily-finalize.log'

if (-not (Test-Path $collector) -or -not (Test-Path $generator)) {
    Write-Host ('ERROR: source files not found under ' + $proj)
    exit 1
}
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$pythonCandidates = @()
if (-not [string]::IsNullOrWhiteSpace($PythonExe)) {
    $pythonCandidates += $PythonExe
} else {
    $pythonCandidates += Get-Command python -All -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Source
    $pythonCandidates += & where.exe python 2>$null
}
$python = $null
foreach ($candidate in ($pythonCandidates | Select-Object -Unique)) {
    if ([string]::IsNullOrWhiteSpace($candidate) -or -not (Test-Path $candidate)) { continue }
    if ($candidate -match '\\hermes-agent\\' -or $candidate -match '\\WindowsApps\\') { continue }
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    & $candidate -c 'import flask, markdown' 2>$null
    $dependencyCheckExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorAction
    if ($dependencyCheckExitCode -eq 0) {
        $python = $candidate
        break
    }
}
if (-not $python) {
    throw 'No stable Python with flask and markdown was found. Pass -PythonExe with a valid interpreter.'
}

$collectTask = 'AIRadarCollectEvery2Hours'
$finalizeTask = 'AIRadarDailyFinalize'
$legacyTask = 'AIRadarDailyUpdate'
foreach ($taskName in @($collectTask, $finalizeTask, $legacyTask)) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
}

$encodingCommand = '[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); $OutputEncoding = [Console]::OutputEncoding'
$collectCommand = "$encodingCommand; & '$python' '$collector' 2>&1 | Out-File -FilePath '$collectLog' -Append -Encoding utf8"
$finalizeCommand = "$encodingCommand; & '$python' '$generator' --finalize-pending 2>&1 | Out-File -FilePath '$finalizeLog' -Append -Encoding utf8"
$collectAction = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -Command "' + $collectCommand.Replace('"','\"') + '"') `
    -WorkingDirectory $proj
$finalizeAction = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -Command "' + $finalizeCommand.Replace('"','\"') + '"') `
    -WorkingDirectory $proj

$collectTimes = 0..11 | ForEach-Object {
    New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours($_ * 2))
}
$retryMinutes = @(5, 20, 35, 50) | ForEach-Object {
    New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddMinutes($_))
}
$collectSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
$finalizeSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

Register-ScheduledTask -TaskName $collectTask -Action $collectAction -Trigger $collectTimes `
    -Settings $collectSettings -Description 'AI Radar: collect the current day information pool every two hours' | Out-Null
Register-ScheduledTask -TaskName $finalizeTask -Action $finalizeAction -Trigger $retryMinutes `
    -Settings $finalizeSettings -Description 'AI Radar: finalize one pending report, yesterday first, with bounded retries' | Out-Null

foreach ($taskName in @($collectTask, $finalizeTask)) {
    if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
        throw "Scheduled task verification failed: $taskName was not found after registration."
    }
}

$userKey = [Environment]::GetEnvironmentVariable('OPENAI_API_KEY', 'User')
if ([string]::IsNullOrWhiteSpace($userKey)) {
    Write-Warning 'OPENAI_API_KEY is not set in User environment variables; scheduled finalization will fail until it is configured.'
}

Write-Host ('Scheduled task registered: ' + $collectTask)
Write-Host ('  python : ' + $python)
Write-Host '  times  : every 2 hours at :00'
Write-Host ('  script : ' + $collector)
Write-Host ('  log    : ' + $collectLog)
Write-Host ('Scheduled task registered: ' + $finalizeTask)
Write-Host '  times  : 00:05, 00:20, 00:35, 00:50'
Write-Host ('  script : ' + $generator + ' --finalize-pending')
Write-Host ('  log    : ' + $finalizeLog)
