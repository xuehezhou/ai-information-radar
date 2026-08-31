@echo off
setlocal
cd /d "%~dp0"
title AI Radar - APK Builder

REM ============================================================
REM  AI Radar APK build script
REM  Requires: android/toolchain/ (build-tools + android.jar + JDK17)
REM  Output:   android/dist/ai-radar.apk
REM  Pure ASCII only - cmd.exe misparses UTF-8 in .bat files.
REM ============================================================

set "BT=toolchain\build-tools"
set "JV=toolchain\jdk-17.0.11+9"
set "KS=release.jks"
set "KSPASS=airiradar2026"

REM ---------- clean ----------
if exist gen rmdir /s /q gen
if exist build rmdir /s /q build
if exist classes rmdir /s /q classes
if exist dexout rmdir /s /q dexout
if not exist dist mkdir dist
mkdir gen build classes dexout

echo [0/6] bundle daily reports into assets/
python -X utf8 bundle_reports.py
if errorlevel 1 goto :fail

echo [1/6] aapt2 compile resources
"%BT%\aapt2.exe" compile --dir res -o build\res.zip
if errorlevel 1 goto :fail

echo [2/6] aapt2 link + generate R.java (embed assets)
"%BT%\aapt2.exe" link -o build\base.apk -I toolchain\android.jar --manifest AndroidManifest.xml -R build\res.zip -A assets --java gen --min-sdk-version 24 --target-sdk-version 34 --auto-add-overlay
if errorlevel 1 goto :fail

echo [3/6] javac
"%JV%\bin\javac.exe" -encoding UTF-8 -classpath toolchain\android.jar -d classes java\com\airiradar\app\MainActivity.java java\com\airiradar\app\ReaderActivity.java gen\com\airiradar\app\R.java
if errorlevel 1 goto :fail

echo [4/6] d8 dex (bundle classes to jar first)
"%JV%\bin\jar.exe" --create --file build\classes.jar -C classes .
"%JV%\bin\java.exe" -cp "%BT%\lib\d8.jar" com.android.tools.r8.D8 --release --lib toolchain\android.jar --output dexout build\classes.jar
if errorlevel 1 goto :fail

echo [5/6] package + align + sign
python -X utf8 -c "import zipfile; z=zipfile.ZipFile('build/base.apk','a',zipfile.ZIP_DEFLATED); z.write('dexout/classes.dex','classes.dex'); z.close()"
"%BT%\zipalign.exe" -f 4 build\base.apk build\aligned.apk
if errorlevel 1 goto :fail

if not exist "%KS%" (
  echo   creating signing keystore...
  "%JV%\bin\keytool.exe" -genkeypair -keystore "%KS%" -alias airiradar -keyalg RSA -keysize 2048 -validity 10000 -storepass %KSPASS% -keypass %KSPASS% -dname "CN=AI Radar, OU=Dev, O=ai-radar, L=Beijing, C=CN"
  if errorlevel 1 goto :fail
)

echo [6/6] apksigner sign
"%JV%\bin\java.exe" -jar "%BT%\lib\apksigner.jar" sign --ks "%KS%" --ks-pass pass:%KSPASS% --key-pass pass:%KSPASS% --out dist\ai-radar.apk build\aligned.apk
if errorlevel 1 goto :fail

echo.
echo  BUILD OK: dist\ai-radar.apk
exit /b 0

:fail
echo.
echo  BUILD FAILED
exit /b 1
