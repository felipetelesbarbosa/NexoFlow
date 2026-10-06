@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Ambiente virtual nao encontrado. Execute instalar.bat primeiro.
    if not defined NEXOFLOW_LAUNCHER pause
    exit /b 1
)

".venv\Scripts\python.exe" run_diagnostico.py
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not defined NEXOFLOW_LAUNCHER pause
exit /b %EXIT_CODE%
