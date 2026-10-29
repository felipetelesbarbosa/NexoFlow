@echo off
chcp 65001 >nul
setlocal
for %%I in ("%~dp0..") do set "NEXOFLOW_HOME=%%~fI"
set "PYTHONPATH=%NEXOFLOW_HOME%;%NEXOFLOW_HOME%\app;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PROFILE_LOG=logs"
set "IMPORT_DIR=importacoes"
if /i "%NEXOFLOW_PERFIL%"=="PET" set "PROFILE_LOG=logs\PET"
if /i "%NEXOFLOW_PERFIL%"=="PET" set "IMPORT_DIR=importacoes\PET"
cd /d "%NEXOFLOW_HOME%\"
title NexoFlow Weni - Dry Run

if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual não encontrado. Execute instalar.bat primeiro.
    if not defined NEXOFLOW_LAUNCHER pause
    exit /b 1
)

".venv\Scripts\python.exe" app\run_update_weni.py --dry-run
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not defined NEXOFLOW_LAUNCHER pause
exit /b %EXIT_CODE%
