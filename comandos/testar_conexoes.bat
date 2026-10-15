@echo off
chcp 65001 >nul
setlocal
for %%I in ("%~dp0..") do set "NEXOFLOW_HOME=%%~fI"
set "PYTHONPATH=%NEXOFLOW_HOME%;%NEXOFLOW_HOME%\app;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
cd /d "%NEXOFLOW_HOME%\"

if not exist ".venv\Scripts\python.exe" (
    echo Ambiente virtual não encontrado. Execute instalar.bat primeiro.
    if not defined NEXOFLOW_LAUNCHER pause
    exit /b 1
)

".venv\Scripts\python.exe" app\run_diagnostico.py
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not defined NEXOFLOW_LAUNCHER pause
exit /b %EXIT_CODE%
