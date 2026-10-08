@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
title NexoFlow Weni
set "NEXOFLOW_LAUNCHER=1"

cls
echo ==========================================================
echo NexoFlow Weni
echo ==========================================================
echo.
echo Rotina segura de atualização de contatos/campos da Weni:
echo   1. Check-up completo do projeto
echo   2. Teste das conexões do NexoFlow Weni
echo   3. Dry-run + auditoria obrigatória do plano
echo   4. Confirmação manual
echo   5. Nova auditoria + aplicação incremental
echo.
echo Nenhum POST na Weni ocorre antes da auditoria do plano.
echo ==========================================================
echo.

call "%~dp0check-up.bat"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro_checkup

echo.
call "%~dp0testar_update_weni.bat"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro_conexoes

echo.
echo [ETAPA 3/5] Dry-run e auditoria do plano
echo ----------------------------------------------------------
".venv\Scripts\python.exe" run_update_weni.py --dry-run
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro_dryrun

echo.
echo ==========================================================
echo DRY-RUN APROVADO. Nenhum dado foi alterado até aqui.
echo ==========================================================
echo.
set /p "CONFIRMA=Digite ATUALIZAR para gravar as mudancas na Weni: "
if /I not "%CONFIRMA%"=="ATUALIZAR" (
    echo.
    echo [INFO] Operação cancelada. Nenhuma alteração foi aplicada.
    pause
    exit /b 2
)

echo.
echo [ETAPA 5/5] Auditoria final e aplicação incremental
echo ----------------------------------------------------------
".venv\Scripts\python.exe" run_update_weni.py --apply
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro_apply

echo.
echo ==========================================================
echo [OK] NexoFlow Weni concluído com sucesso.
echo Auditoria: OK ^| Gravação: OK
echo ==========================================================
echo.
pause
exit /b 0

:erro_checkup
echo.
echo [ERRO] Check-up falhou. Nenhuma alteração foi feita na Weni.
pause
exit /b %RC%

:erro_conexoes
echo.
echo [ERRO] Teste de conexões falhou. Nenhuma alteração foi feita na Weni.
pause
exit /b %RC%

:erro_dryrun
echo.
echo [ERRO] Dry-run/auditoria falhou. Nenhuma alteração foi feita na Weni.
pause
exit /b %RC%

:erro_apply
echo.
echo [ERRO] A aplicação foi interrompida.
echo O checkpoint NÃO foi avançado. Execute novamente após corrigir o problema.
echo Consulte logs\nexoflow_update_weni.log e logs\weni_update_audit.jsonl.
pause
exit /b %RC%
