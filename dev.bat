@echo off
REM 开发态运行: dev.bat [--capture|--selftest|--bench|--settings]
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe src\run.py %*
