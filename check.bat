@echo off
REM 质量门禁：格式 + 静态检查 + 探针 + 自检（见 docs\10-代码审查标准与流程.md）
REM 用法: check.bat [--fast] [--skip-ruff]
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe scripts\gate.py %*
