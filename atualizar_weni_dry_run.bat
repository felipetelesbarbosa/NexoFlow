@echo off
chcp 65001 >nul
setlocal
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
title NexoFlow Weni - Dry Run

if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual não encontrado. Execute instalar.bat primeiro.
    if not defined NEXOFLOW_LAUNCHER pause
    exit /b 1
)

".venv\Scripts\python.exe" run_update_weni.py --dry-run
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not defined NEXOFLOW_LAUNCHER pause
exit /b %EXIT_CODE%
