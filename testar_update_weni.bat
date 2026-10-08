@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title NexoFlow - Teste Weni

if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual não encontrado. Execute instalar.bat primeiro.
    if not defined NEXOFLOW_LAUNCHER pause
    exit /b 1
)

".venv\Scripts\python.exe" run_update_weni.py --check-only
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not defined NEXOFLOW_LAUNCHER pause
exit /b %EXIT_CODE%
