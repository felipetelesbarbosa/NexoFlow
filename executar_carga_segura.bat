@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title NexoFlow - Sincronizacao Manual

set "NEXOFLOW_LAUNCHER=1"

echo ==========================================================
echo NexoFlow - Sincronizacao Manual Segura
echo ==========================================================
echo.
echo Esta rotina executara, em ordem:
echo   1. Check-up do projeto
echo   2. Teste de conexoes
echo   3. Sincronizacao incremental manual
echo.
echo Se uma etapa falhar, as proximas NAO serao executadas.
echo ==========================================================
echo.

echo [ETAPA 1/3] Check-up do projeto
echo ----------------------------------------------------------
call "%~dp0check-up.bat"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro_checkup

echo.
echo [ETAPA 2/3] Teste de conexoes
echo ----------------------------------------------------------
call "%~dp0testar_conexoes.bat"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro_conexoes

echo.
echo [ETAPA 3/3] Sincronizacao incremental
echo ----------------------------------------------------------
call "%~dp0executar_manual.bat"
set "RC=%ERRORLEVEL%"
if "%RC%"=="3" goto :parcial
if not "%RC%"=="0" goto :erro_sync

echo.
echo ==========================================================
echo [OK] Processo concluido com sucesso.
echo Check-up: OK ^| Conexoes: OK ^| Sincronizacao: OK
echo ==========================================================
echo.
pause
exit /b 0

:parcial
echo.
echo ==========================================================
echo [AVISO] Sincronizacao parcial: algumas consultas a FarmaLider falharam.
echo Os dados processados foram salvos; o marco incremental anterior foi
echo mantido para nova tentativa. Consulte logs\nexoflow.log.
echo Codigo de saida: %RC%
echo ==========================================================
echo.
pause
exit /b %RC%

:erro_checkup
echo.
echo ==========================================================
echo [ERRO] O check-up falhou. A sincronizacao NAO foi iniciada.
echo Codigo de saida: %RC%
echo ==========================================================
echo.
pause
exit /b %RC%

:erro_conexoes
echo.
echo ==========================================================
echo [ERRO] O teste de conexoes falhou. A sincronizacao NAO foi iniciada.
echo Codigo de saida: %RC%
echo ==========================================================
echo.
pause
exit /b %RC%

:erro_sync
echo.
echo ==========================================================
echo [ERRO] A sincronizacao terminou com erro.
echo Codigo de saida: %RC%
echo Consulte o log em logs\nexoflow.log
echo ==========================================================
echo.
pause
exit /b %RC%
