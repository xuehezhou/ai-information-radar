@echo off
setlocal
chcp 65001 >nul
title AI Information Radar
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_source.ps1" %*
if errorlevel 1 pause
endlocal
