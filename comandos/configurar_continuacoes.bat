@echo off
chcp 65001 >nul
setlocal
for %%I in ("%~dp0..") do set "NEXOFLOW_HOME=%%~fI"
set "PYTHONPATH=%NEXOFLOW_HOME%;%NEXOFLOW_HOME%\app;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
cd /d "%NEXOFLOW_HOME%\"
if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente Python ausente. Execute o Setup.
    pause
    exit /b 2
)
".venv\Scripts\python.exe" app\run_sheets_console.py %*
exit /b %errorlevel%
