param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$appPath = Join-Path $projectRoot 'src\app.py'
$logDir = Join-Path $projectRoot 'data\logs'
$stdoutLog = Join-Path $logDir 'source-server.stdout.log'
$stderrLog = Join-Path $logDir 'source-server.stderr.log'
$port = 8899
$baseUrl = "http://127.0.0.1:$port"
$expectedProjectId = 'ai-radar-portable-source'
$packagedProcessName = 'AI' + [char]0x4FE1 + [char]0x606F + [char]0x96F7 + [char]0x8FBE

function Show-LauncherError([string]$message) {
    Write-Host "ERROR: $message" -ForegroundColor Red
    try {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show(
            $message,
            'AI Information Radar',
            'OK',
            'Error'
        ) | Out-Null
    } catch {
        # Console output remains available when the message box cannot be shown.
    }
}

function Get-ListenerProcessId {
    $pattern = "^\s*TCP\s+\S+:$port\s+\S+\s+LISTENING\s+(\d+)\s*$"
    foreach ($line in (& netstat.exe -ano -p tcp)) {
        if ($line -match $pattern) { return [int]$Matches[1] }
    }
    return $null
}

function Get-SourceInstance {
    try {
        return Invoke-RestMethod "$baseUrl/api/instance" -TimeoutSec 2
    } catch {
        return $null
    }
}

function Test-SourceFilesNewerThan([datetime]$processStartTime) {
    $latestSource = Get-ChildItem (Join-Path $projectRoot 'src') -Recurse -File |
        Where-Object { $_.Extension -in '.py', '.html', '.css', '.js' } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    return $latestSource -and $latestSource.LastWriteTime -gt $processStartTime
}

function Stop-KnownOldRadarProcesses {
    Get-Process -Name $packagedProcessName -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            Stop-Process -Id $_.Id -Force
            Write-Host "Stopped old packaged instance: PID $($_.Id)"
        } catch {
            throw "Unable to stop old packaged instance PID $($_.Id): $($_.Exception.Message)"
        }
    }
}

try {
    if (-not (Test-Path $appPath)) {
        throw "Main source entry does not exist: $appPath"
    }

    $listenerProcessId = Get-ListenerProcessId
    $instance = Get-SourceInstance

    if ($instance.project_id -eq $expectedProjectId) {
        if ($listenerProcessId) {
            $runningProcess = Get-Process -Id $listenerProcessId -ErrorAction Stop
            if (Test-SourceFilesNewerThan $runningProcess.StartTime) {
                Write-Host 'Source files changed after the current server started; restarting.'
                Stop-Process -Id $listenerProcessId -Force
                Start-Sleep -Milliseconds 500
            } else {
                Write-Host "Latest source instance is already running: $baseUrl"
                if (-not $NoBrowser) { Start-Process $baseUrl }
                exit 0
            }
        } else {
            Write-Host "Verified source instance is already running: $baseUrl"
            if (-not $NoBrowser) { Start-Process $baseUrl }
            exit 0
        }
    } elseif ($listenerProcessId) {
        $listener = Get-Process -Id $listenerProcessId -ErrorAction SilentlyContinue
        $listenerPath = if ($listener) { $listener.Path } else { '' }
        if ($listener -and $listener.ProcessName -eq $packagedProcessName) {
            Stop-Process -Id $listenerProcessId -Force
            Start-Sleep -Milliseconds 500
        } else {
            throw "Port $port is occupied by another program (PID $listenerProcessId). Startup stopped to avoid opening the wrong version."
        }
    }

    Stop-KnownOldRadarProcesses

    foreach ($name in 'OPENAI_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_MODEL') {
        $userValue = [Environment]::GetEnvironmentVariable($name, 'User')
        if ($userValue) { Set-Item "Env:$name" $userValue }
    }
    $env:AI_RADAR_PORT = "$port"
    $env:AI_RADAR_STRICT_PORT = '1'

    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { $pythonCommand = Get-Command python -ErrorAction SilentlyContinue }
    if (-not $pythonCommand) { throw 'Python was not found. Install Python 3.10+ first.' }

    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    Start-Process -FilePath $pythonCommand.Source `
        -ArgumentList @($appPath) `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog | Out-Null

    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        $instance = Get-SourceInstance
        if ($instance.project_id -eq $expectedProjectId) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        throw "The source service did not start at $baseUrl. Check $stderrLog"
    }

    Write-Host "Latest source instance started: $baseUrl"
    if (-not $NoBrowser) { Start-Process $baseUrl }
    exit 0
} catch {
    Show-LauncherError $_.Exception.Message
    exit 1
}
