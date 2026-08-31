@echo off
chcp 65001 >nul
title AI信息雷达 · 便携版
cd /d "%~dp0"

REM ===== fix proxy bypass for localhost (work under any proxy) =====
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyOverride /t REG_SZ /d "localhost;127.*;<local>" /f >nul 2>&1

echo ============================================
echo   AI信息雷达 · 便携版启动器
echo ============================================

REM ---------- 1. 查找 Python ----------
set "PY="
for %%P in (
  "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
  "%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe"
  "C:\Python313\pythonw.exe"
  "C:\Python312\pythonw.exe"
  "C:\Python311\pythonw.exe"
  "C:\Python310\pythonw.exe"
  "D:\anaconda3\pythonw.exe"
  "%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw.exe"
) do (
  if exist %%P set "PY=%%P"
)
if not defined PY (
  where pythonw >nul 2>nul && set "PY=pythonw"
)
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo [需要安装 Python] 这台电脑还没有 Python。
  echo 请到 https://www.python.org/downloads/ 下载安装 Python 3.10+，
  echo 安装时勾选 "Add python.exe to PATH"，装完再双击本文件即可。
  echo.
  pause
  exit /b 1
)
echo 使用 Python: %PY%

REM ---------- 2. 已在运行？直接打开 ----------
netstat -ano | findstr ":8899" | findstr "LISTENING" >nul
if not errorlevel 1 (
  echo 服务已在运行，打开 http://127.0.0.1:8899 ...
  start "" http://127.0.0.1:8899
  exit /b 0
)

REM ---------- 3. 检查依赖，缺失则自动安装 ----------
if not exist "data" mkdir data
"%PY%" -c "import flask, markdown" >nul 2>nul
if errorlevel 1 (
  echo 首次运行，正在安装依赖（flask、markdown）...
  "%PY%" -m pip install --user -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
  )
)

REM ---------- 4. 后台启动 ----------
start "" /B "%PY%" "src\app.py" > data\server_stdout.log 2>&1

REM ---------- 5. 等待就绪 ----------
set /a tries=0
:wait_loop
netstat -ano | findstr ":8899" | findstr "LISTENING" >nul
if not errorlevel 1 goto ready
set /a tries+=1
if %tries% GEQ 20 (
  echo [ERROR] 启动失败，请查看 data\server_stdout.log
  pause
  exit /b 1
)
ping -n 2 127.0.0.1 >nul
goto wait_loop

:ready
echo 服务已就绪，正在打开浏览器...
start "" http://127.0.0.1:8899
echo 服务在后台运行，本窗口可关闭。
timeout /t 3 >nul
exit /b 0
