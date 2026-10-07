@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title NexoFlow Analytics - Carga Completa

if not exist ".venv\Scripts\python.exe" (
    echo Ambiente virtual nao encontrado. Execute instalar.bat primeiro.
    pause
    exit /b 1
)

cls
echo ==========================================================
echo NexoFlow Analytics - Carga Completa
echo ==========================================================
echo.
echo Escolha o tamanho da carga:
echo.
echo   [0] 100%% - carga completa tradicional
echo   [1] Parte 1/4 - primeiros 25%%
echo   [2] Parte 2/4 - segundos 25%%
echo   [3] Parte 3/4 - terceiros 25%%
echo   [4] Parte 4/4 - ultimos 25%%
echo.
echo As partes 25%% NAO sao incrementais.
echo Elas usam uma base congelada e devem ser executadas em ordem.
echo.
set /p "OPCAO=Opcao: "

set "FULL_SYNC_QUARTER="
if "%OPCAO%"=="0" goto :executar
if "%OPCAO%"=="1" set "FULL_SYNC_QUARTER=1"
if "%OPCAO%"=="2" set "FULL_SYNC_QUARTER=2"
if "%OPCAO%"=="3" set "FULL_SYNC_QUARTER=3"
if "%OPCAO%"=="4" set "FULL_SYNC_QUARTER=4"
if not defined FULL_SYNC_QUARTER (
    echo [ERRO] Opcao invalida.
    pause
    exit /b 2
)

:executar
set "FORCE_FULL_SYNC=1"
if defined FULL_SYNC_QUARTER (
    echo.
    echo [INFO] Executando Analytics - carga completa 25%% Parte %FULL_SYNC_QUARTER%/4.
    echo [INFO] As outras partes nao serao processadas nesta execucao.
) else (
    echo.
    echo [INFO] Executando Analytics - carga completa tradicional 100%%.
)

".venv\Scripts\python.exe" run_main.py
set "EXIT_CODE=%ERRORLEVEL%"
set "FORCE_FULL_SYNC="
set "FULL_SYNC_QUARTER="

echo.
echo Codigo de saida: %EXIT_CODE%
if "%EXIT_CODE%"=="3" (
    echo [AVISO] Sincronizacao parcial. A parte NAO foi marcada como concluida.
    echo Execute novamente a mesma parte depois de consultar logs\nexoflow.log.
)
if "%EXIT_CODE%"=="0" echo [OK] Carga concluida.
pause
exit /b %EXIT_CODE%
