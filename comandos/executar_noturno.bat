@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
for %%I in ("%~dp0..") do set "NEXOFLOW_HOME=%%~fI"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%NEXOFLOW_HOME%;%NEXOFLOW_HOME%\app;%PYTHONPATH%"
cd /d "%NEXOFLOW_HOME%\"
title NexoFlow Noturno
if not exist "%NEXOFLOW_HOME%\.venv\Scripts\python.exe" goto :ambiente_ausente
"%NEXOFLOW_HOME%\.venv\Scripts\python.exe" "%NEXOFLOW_HOME%\app\run_noturno_console.py" %*
exit /b %errorlevel%
:ambiente_ausente
echo [ERRO] Ambiente Python ausente. Execute o Setup para reparar a instalação.
echo O resultado permanecerá nesta janela. Digite EXIT para fechar.
:aguardar
set "RESPOSTA="
set /p "RESPOSTA=> " || exit /b 2
if /i not "%RESPOSTA%"=="EXIT" goto :aguardar
exit /b 2
