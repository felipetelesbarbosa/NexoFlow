@echo off
chcp 65001 >nul
setlocal
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Ambiente virtual não encontrado. Execute instalar.bat primeiro.
    if not defined NEXOFLOW_LAUNCHER pause
    exit /b 1
)

".venv\Scripts\python.exe" run_diagnostico.py
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not defined NEXOFLOW_LAUNCHER pause
exit /b %EXIT_CODE%
