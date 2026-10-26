@echo off
REM One-click Windows build: portable zip (onedir) + installer (setup.exe)
REM NOTE: PyQt5 Qt-plugin detection fails under non-ASCII paths.
REM       Copy the project to an ASCII path first (see docs/04).
REM This file MUST stay UTF-8 (no BOM) with CRLF. The chcp below makes cmd
REM decode the Chinese text correctly regardless of console codepage.
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."
set VENV=%CD%\.venv

echo [1/4] PyInstaller (onedir)...
"%VENV%\Scripts\python.exe" -m PyInstaller --noconfirm --clean deploy\snapocr.spec || goto :err

echo [2/4] Building portable zip...
if exist "dist\SnapOCR-1.0.0-win64-绿色版.zip" del "dist\SnapOCR-1.0.0-win64-绿色版.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\snapocr-win64\*' -DestinationPath 'dist\SnapOCR-1.0.0-win64-绿色版.zip' -Force" || goto :err

echo [3/4] Locating Inno Setup (ISCC)...
REM Inno Setup 7 first (current release env), 6.x as fallback
set ISCC="%ProgramFiles%\Inno Setup 7\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
    echo   Inno Setup not found, skipping installer.
    echo [OK] portable zip: dist\SnapOCR-1.0.0-win64-绿色版.zip
    exit /b 0
)

echo [4/4] Building installer...
%ISCC% deploy\windows\snapocr.iss || goto :err
echo [OK] done:
echo   dist\SnapOCR-1.0.0-win64-portable.zip  (release asset name)
echo   dist\SnapOCR-1.0.0-win64-setup.exe
exit /b 0

:err
echo [FAIL] build failed
echo   If the output above was flooded by Compress-Archive progress, rerun with a log:
echo     build_all.bat ^> %TEMP%\snapocr_build.log 2^>^&1
echo   Common causes: free disk ^< 3G (docs/04 1.1), incomplete venv copy, non-ASCII path.
exit /b 1
