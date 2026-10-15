@echo off
chcp 65001 >nul
setlocal EnableExtensions
for %%I in ("%~dp0..") do set "NEXOFLOW_HOME=%%~fI"
set "PYTHONPATH=%NEXOFLOW_HOME%;%NEXOFLOW_HOME%\app;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
cd /d "%NEXOFLOW_HOME%\"
title NexoFlow Analytics - Carga Completa
set "WORKFLOW_MODE="
if /i "%~1"=="--fluxo-completo" set "WORKFLOW_MODE=1"

if not exist ".venv\Scripts\python.exe" (
    echo Ambiente virtual não encontrado. Execute instalar.bat primeiro.
    if not defined WORKFLOW_MODE pause
    exit /b 1
)

if defined WORKFLOW_MODE (
    set "OPCAO=0"
    goto :opcao_escolhida
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
echo   [4] Parte 4/4 - últimos 25%%
echo.
echo As partes 25%% NÃO são incrementais.
echo Elas usam uma base congelada e devem ser executadas em ordem.
echo.
set /p "OPCAO=Opção: "

:opcao_escolhida
set "FULL_SYNC_QUARTER="
if "%OPCAO%"=="0" goto :executar
if "%OPCAO%"=="1" set "FULL_SYNC_QUARTER=1"
if "%OPCAO%"=="2" set "FULL_SYNC_QUARTER=2"
if "%OPCAO%"=="3" set "FULL_SYNC_QUARTER=3"
if "%OPCAO%"=="4" set "FULL_SYNC_QUARTER=4"
if not defined FULL_SYNC_QUARTER (
    echo [ERRO] Opção inválida.
    if not defined WORKFLOW_MODE pause
    exit /b 2
)

:executar
set "FORCE_FULL_SYNC=1"
if defined FULL_SYNC_QUARTER (
    echo.
    echo [INFO] Executando Analytics - carga completa 25%% Parte %FULL_SYNC_QUARTER%/4.
    echo [INFO] As outras partes não serão processadas nesta execução.
) else (
    echo.
    echo [INFO] Executando Analytics - carga completa tradicional 100%%.
)

".venv\Scripts\python.exe" app\run_main.py
set "EXIT_CODE=%ERRORLEVEL%"
set "FORCE_FULL_SYNC="
set "FULL_SYNC_QUARTER="

echo.
echo Código de saída: %EXIT_CODE%
if "%EXIT_CODE%"=="3" (
    echo [AVISO] Sincronização parcial. A parte NÃO foi marcada como concluída.
    echo Execute novamente a mesma parte depois de consultar logs\nexoflow.log.
)
if "%EXIT_CODE%"=="0" echo [OK] Carga concluída.
if not defined WORKFLOW_MODE pause
exit /b %EXIT_CODE%
