@echo off
chcp 65001 >nul
setlocal EnableExtensions
for %%I in ("%~dp0..") do set "NEXOFLOW_HOME=%%~fI"
set "PYTHONPATH=%NEXOFLOW_HOME%;%NEXOFLOW_HOME%\app;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PROFILE_LOG=logs"
set "IMPORT_DIR=importacoes"
if /i "%NEXOFLOW_PERFIL%"=="PET" set "PROFILE_LOG=logs\PET"
if /i "%NEXOFLOW_PERFIL%"=="PET" set "IMPORT_DIR=importacoes\PET"
cd /d "%NEXOFLOW_HOME%\"
title NexoFlow - Sincronização Manual

set "NEXOFLOW_LAUNCHER=1"

echo ==========================================================
echo NexoFlow - Sincronização Manual Segura
echo ==========================================================
echo.
echo Esta rotina executará, em ordem:
echo   1. Check-up do projeto
echo   2. Teste de conexões
echo   3. Sincronização incremental manual
echo.
echo Se uma etapa falhar, as próximas NÃO serão executadas.
echo ==========================================================
echo.

echo [ETAPA 1/3] Check-up do projeto
echo ----------------------------------------------------------
call "%NEXOFLOW_HOME%\comandos\check-up.bat"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro_checkup

echo.
echo [ETAPA 2/3] Teste de conexões
echo ----------------------------------------------------------
call "%NEXOFLOW_HOME%\comandos\testar_conexoes.bat"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro_conexoes

echo.
echo [ETAPA 3/3] Sincronização incremental
echo ----------------------------------------------------------
call "%NEXOFLOW_HOME%\comandos\executar_manual.bat"
set "RC=%ERRORLEVEL%"
if "%RC%"=="3" goto :parcial
if not "%RC%"=="0" goto :erro_sync

echo.
echo ==========================================================
echo [OK] Processo concluído com sucesso.
echo Check-up: OK ^| Conexões: OK ^| Sincronização: OK
echo ==========================================================
echo.
pause
exit /b 0

:parcial
echo.
echo ==========================================================
echo [AVISO] Sincronização parcial: algumas consultas à FarmaLíder falharam.
echo Os dados processados foram salvos; o marco incremental anterior foi
echo mantido para nova tentativa. Consulte logs\nexoflow.log.
echo Código de saída: %RC%
echo ==========================================================
echo.
pause
exit /b %RC%

:erro_checkup
echo.
echo ==========================================================
echo [ERRO] O check-up falhou. A sincronização NÃO foi iniciada.
echo Código de saída: %RC%
echo ==========================================================
echo.
pause
exit /b %RC%

:erro_conexoes
echo.
echo ==========================================================
echo [ERRO] O teste de conexões falhou. A sincronização NÃO foi iniciada.
echo Código de saída: %RC%
echo ==========================================================
echo.
pause
exit /b %RC%

:erro_sync
echo.
echo ==========================================================
echo [ERRO] A sincronização terminou com erro.
echo Código de saída: %RC%
echo Consulte o log em logs\nexoflow.log
echo ==========================================================
echo.
pause
exit /b %RC%
