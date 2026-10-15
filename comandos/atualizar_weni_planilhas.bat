@echo off
chcp 65001 >nul
setlocal
for %%I in ("%~dp0..") do set "NEXOFLOW_HOME=%%~fI"
set "PYTHONPATH=%NEXOFLOW_HOME%;%NEXOFLOW_HOME%\app;%PYTHONPATH%"
call "%NEXOFLOW_HOME%\comandos\carga_planilhas.bat" weni
exit /b %ERRORLEVEL%
