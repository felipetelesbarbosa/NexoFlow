@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Ambiente virtual nao encontrado. Execute instalar.bat primeiro.
    if not defined NEXOFLOW_LAUNCHER pause
    exit /b 1
)

".venv\Scripts\python.exe" run_main.py
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo Codigo de saida: %EXIT_CODE%
if "%EXIT_CODE%"=="3" echo [AVISO] Sincronizacao parcial; consulte logs\nexoflow.log.
if not defined NEXOFLOW_LAUNCHER pause
exit /b %EXIT_CODE%
