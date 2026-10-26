@echo off
chcp 65001 >nul
rem Abrir a interface de comandos do NexoFlow.
setlocal
for %%I in ("%~dp0") do set "NEXOFLOW_HOME=%%~fI"
set "PYTHONPATH=%NEXOFLOW_HOME%;%NEXOFLOW_HOME%\app;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "NEXO_HOME=%NEXOFLOW_HOME%\"
if exist "%NEXO_HOME%.venv\Scripts\python.exe" (
  "%NEXO_HOME%.venv\Scripts\python.exe" "%NEXO_HOME%app\nexo_cli.py" %*
) else (
  python "%NEXO_HOME%app\nexo_cli.py" %*
)
exit /b %errorlevel%
