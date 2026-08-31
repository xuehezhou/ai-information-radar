# ASCII-only source: build Chinese name from codepoints, rename the fixed shortcut
# Target name: AI信息雷达.lnk
$cn = [string]([char]0x4FE1) + [string]([char]0x606F) + [string]([char]0x96F7) + [string]([char]0x8FBE)  # xin xi lei da
$newName = 'AI' + $cn + '.lnk'

$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')

# Find shortcut targeting start.bat
$lnk = Get-ChildItem $desktop -Filter '*.lnk' -ErrorAction SilentlyContinue | Where-Object {
    ($ws.CreateShortcut($_.FullName)).TargetPath -like '*start.bat'
} | Select-Object -First 1

if (-not $lnk) { Write-Host "No start.bat shortcut found"; exit 1 }

$newPath = Join-Path $desktop $newName
if ($lnk.FullName -ne $newPath) {
    if (Test-Path $newPath) { Remove-Item $newPath -Force }
    Rename-Item -Path $lnk.FullName -NewName $newName
    Write-Host ("Renamed to: " + $newPath)
} else {
    Write-Host "Already has correct name"
}

# Verify final state
$final = Get-ChildItem $desktop -Filter '*.lnk' | Where-Object { ($ws.CreateShortcut($_.FullName)).TargetPath -like '*start.bat' }
$s = $ws.CreateShortcut($final.FullName)
Write-Host ("File : " + $final.FullName)
Write-Host ("Target: " + $s.TargetPath + " | exists=" + (Test-Path $s.TargetPath))
$cp = ($final.Name.ToCharArray() | ForEach-Object { "U+{0:X4}" -f [int]$_ }) -join ' '
Write-Host ("Name codepoints: " + $cp)
