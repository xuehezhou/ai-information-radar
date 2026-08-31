$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$launcher = Join-Path $projectRoot 'start.bat'
$iconPath = Join-Path $projectRoot 'assets\ai-radar.ico'
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutName = 'AI' + [char]0x4FE1 + [char]0x606F + [char]0x96F7 + [char]0x8FBE + '.lnk'
$shortcutPath = Join-Path $desktop $shortcutName
$ws = New-Object -ComObject WScript.Shell
$shortcut = $ws.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcher
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = "$iconPath,0"
$shortcut.Description = 'AI Information Radar - Main Source Edition'
$shortcut.Save()
Write-Host "Shortcut created: $shortcutPath -> $launcher"
