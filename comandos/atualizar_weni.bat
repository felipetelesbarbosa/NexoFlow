@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
if not defined NEXOFLOW_NETWORK_SESSION set "NEXOFLOW_NETWORK_SESSION=bat-%RANDOM%-%RANDOM%-%RANDOM%-%RANDOM%"
for %%I in ("%~dp0..") do set "NEXOFLOW_HOME=%%~fI"
set "PYTHONPATH=%NEXOFLOW_HOME%;%NEXOFLOW_HOME%\app;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PROFILE_LOG=logs"
set "IMPORT_DIR=importacoes"
if /i "%NEXOFLOW_PERFIL%"=="PET" set "PROFILE_LOG=logs\PET"
if /i "%NEXOFLOW_PERFIL%"=="PET" set "IMPORT_DIR=importacoes\PET"
cd /d "%NEXOFLOW_HOME%\"
title NexoFlow Weni
set "NEXOFLOW_LAUNCHER=1"
set "FINAL_RC=0"

if not exist "%NEXOFLOW_HOME%\scripts\confirmar_revisao_weni.ps1" (
    echo [ERRO] Componente de confirmação ausente: scripts\confirmar_revisao_weni.ps1
    echo Reinstale o Setup atualizado do NexoFlow 1.5.31 antes de continuar.
    call :aguardar_saida
    exit /b 1
)

cls
echo ==========================================================
echo NexoFlow Weni
echo ==========================================================
echo.
echo Rotina segura de atualização de contatos/campos da Weni:
echo   1. Check-up completo do projeto
echo   2. Teste das conexões do NexoFlow Weni
echo   3. Dry-run + auditoria de campos e contatos duplicados
echo   4. Confirmação manual
echo   5. Nova auditoria + aplicação incremental
echo.
echo Nenhum POST na Weni ocorre antes da auditoria do plano.
echo ==========================================================
echo.

call "%NEXOFLOW_HOME%\comandos\check-up.bat"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro_checkup

echo.
call "%NEXOFLOW_HOME%\comandos\testar_update_weni.bat"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro_conexoes

echo.
echo [ETAPA 3/5] Dry-run e auditoria do plano
echo ----------------------------------------------------------
".venv\Scripts\python.exe" app\run_update_weni.py --dry-run
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro_dryrun

echo.
echo ==========================================================
echo DRY-RUN APROVADO. Nenhum dado foi alterado até aqui.
echo ==========================================================
echo.
echo [INFO] A confirmação será solicitada em uma janela separada.
echo [INFO] Revise também as exclusões propostas em logs\weni_update_review.txt.
echo [INFO] Encerre outras cargas de Analytics, Planilhas e Recompra.
start "" notepad.exe "%NEXOFLOW_HOME%\%PROFILE_LOG%\weni_update_review.txt" >nul 2>&1
echo [INFO] Digite ATUALIZAR apenas depois de revisar o relatório do dry-run.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%NEXOFLOW_HOME%\scripts\confirmar_revisao_weni.ps1" -Expected "ATUALIZAR" -Title "NexoFlow Weni - Confirmacao Incremental"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo [INFO] Operação cancelada. Nenhuma alteração foi aplicada.
    call :aguardar_saida
    exit /b 2
)

echo.
echo [ETAPA 5/5] Auditoria final e aplicação incremental
echo ----------------------------------------------------------
".venv\Scripts\python.exe" app\run_update_weni.py --apply
set "RC=%ERRORLEVEL%"
if "%RC%"=="3" set "FINAL_RC=3"
if not "%RC%"=="0" if not "%RC%"=="3" goto :erro_apply

echo.
echo ==========================================================
rem Recompra é uma etapa independente, com auditoria e revisão próprias.
".venv\Scripts\python.exe" -c "import sys,secrets_config as s; sys.exit(0 if getattr(s,'RECOMPRA_ENABLED',False) else 10)"
if not "%ERRORLEVEL%"=="0" goto :recompra_desabilitada
call "%NEXOFLOW_HOME%\comandos\atualizar_recompra.bat"
set "RC=%ERRORLEVEL%"
if "%RC%"=="3" goto :recompra_parcial
if not "%RC%"=="0" goto :erro_recompra
goto :recompra_fim
:recompra_parcial
set "FINAL_RC=3"
echo [AVISO] Weni concluída; etapa Recompra com pendências de validação.
echo As alterações já confirmadas foram preservadas.
echo Consulte o resumo da Recompra para conferir inclusões confirmadas e contatos para revalidar.
goto :recompra_fim
:recompra_desabilitada
echo [INFO] Etapa Recompra não executada: RECOMPRA_ENABLED=False.
:recompra_fim
if "%FINAL_RC%"=="0" echo [OK] NexoFlow Weni concluído com sucesso.
if "%FINAL_RC%"=="3" echo [AVISO] Fluxo Weni concluído com pendências. Revalide os itens indicados na próxima carga.
echo Consulte os totais confirmados nos resumos de cada etapa.
echo [INFO] O resultado permanecerá no terminal. Digite EXIT quando quiser fechar.
echo ==========================================================
echo.
call :aguardar_saida
exit /b %FINAL_RC%

:erro_recompra
echo [ERRO] Weni concluída; a etapa Recompra foi interrompida com código %RC%.
echo Preserve as alterações confirmadas e confira a auditoria antes de retomar.
echo Consulte %PROFILE_LOG%\nexoflow_recompra.log e %PROFILE_LOG%\recompra_audit.jsonl.
call :aguardar_saida
exit /b %RC%

:erro_checkup
echo.
echo [ERRO] Check-up falhou. Nenhuma alteração foi feita na Weni.
call :aguardar_saida
exit /b %RC%

:erro_conexoes
echo.
echo [ERRO] Teste de conexões falhou. Nenhuma alteração foi feita na Weni.
call :aguardar_saida
exit /b %RC%

:erro_dryrun
echo.
echo [ERRO] Dry-run/auditoria falhou. Nenhuma alteração foi feita na Weni.
call :aguardar_saida
exit /b %RC%

:erro_apply
echo.
echo [ERRO] A aplicação foi interrompida.
echo Confira o checkpoint e a auditoria antes de retomar. As alterações confirmadas permanecem preservadas.
echo Consulte logs\nexoflow_update_weni.log e logs\weni_update_audit.jsonl.
call :aguardar_saida
exit /b %RC%

:aguardar_saida
if defined NEXOFLOW_TERMINAL exit /b 0
setlocal EnableDelayedExpansion
:aguardar_exit
set "WENI_EXIT="
set /p "WENI_EXIT=Digite EXIT para fechar esta janela: " < CON
if /i "!WENI_EXIT!"=="EXIT" goto :saida_confirmada
goto :aguardar_exit
:saida_confirmada
endlocal
exit /b 0
