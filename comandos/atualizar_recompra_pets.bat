@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
if not defined NEXOFLOW_NETWORK_SESSION set "NEXOFLOW_NETWORK_SESSION=bat-%RANDOM%-%RANDOM%-%RANDOM%-%RANDOM%"
for %%I in ("%~dp0..") do set "NEXOFLOW_HOME=%%~fI"
set "PYTHONPATH=%NEXOFLOW_HOME%;%NEXOFLOW_HOME%\app;%PYTHONPATH%"
set "NEXOFLOW_PERFIL=PET"
call "%NEXOFLOW_HOME%\comandos\atualizar_recompra.bat" PET
exit /b %ERRORLEVEL%
