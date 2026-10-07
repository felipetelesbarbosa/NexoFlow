@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Ambiente virtual nao encontrado. Execute instalar.bat primeiro.
    pause
    exit /b 1
)

set "FORCE_FULL_SYNC=1"
".venv\Scripts\python.exe" run_main.py
set "EXIT_CODE=%ERRORLEVEL%"
set "FORCE_FULL_SYNC="

echo.
echo Codigo de saida: %EXIT_CODE%
if "%EXIT_CODE%"=="3" echo [AVISO] Sincronizacao parcial; consulte logs\nexoflow.log.
pause
exit /b %EXIT_CODE%
