@echo off
chcp 65001 >nul
setlocal
for %%I in ("%~dp0") do set "NEXOFLOW_HOME=%%~fI"
set "PYTHONPATH=%NEXOFLOW_HOME%;%NEXOFLOW_HOME%\app;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "NEXOFLOW_HOME=%NEXOFLOW_HOME%\"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%POWERSHELL_EXE%" set "POWERSHELL_EXE=powershell.exe"
"%POWERSHELL_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%NEXOFLOW_HOME%installer\uninstall.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" if not "%RC%"=="2" pause
exit /b %RC%
