@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
if not defined NEXOFLOW_NETWORK_SESSION set "NEXOFLOW_NETWORK_SESSION=bat-%RANDOM%-%RANDOM%-%RANDOM%-%RANDOM%"
for %%I in ("%~dp0..") do set "NEXOFLOW_HOME=%%~fI"
set "PYTHONPATH=%NEXOFLOW_HOME%;%NEXOFLOW_HOME%\app;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
cd /d "%NEXOFLOW_HOME%\"
echo Auditoria somente leitura do grupo de Recompra. Nenhum contato será alterado.
".venv\Scripts\python.exe" app\run_recompra.py --audit-group
set "RC=%ERRORLEVEL%"
echo Código de saída: %RC%
echo Veja os relatórios em logs\privado ou logs\PET\privado, conforme o perfil.
pause
exit /b %RC%
