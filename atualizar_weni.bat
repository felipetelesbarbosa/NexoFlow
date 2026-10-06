@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title NexoFlow Weni
set "NEXOFLOW_LAUNCHER=1"

cls
echo ==========================================================
echo NexoFlow Weni
echo ==========================================================
echo.
echo Rotina segura de atualizacao de contatos/campos da Weni:
echo   1. Check-up completo do projeto
echo   2. Teste das conexoes do NexoFlow Weni
echo   3. Dry-run + auditoria obrigatoria do plano
echo   4. Confirmacao manual
echo   5. Nova auditoria + aplicacao incremental
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
echo DRY-RUN APROVADO. Nenhum dado foi alterado ate aqui.
echo ==========================================================
echo.
set /p "CONFIRMA=Digite ATUALIZAR para gravar as mudancas na Weni: "
if /I not "%CONFIRMA%"=="ATUALIZAR" (
    echo.
    echo [INFO] Operacao cancelada. Nenhuma alteracao foi aplicada.
    pause
    exit /b 2
)

echo.
echo [ETAPA 5/5] Auditoria final e aplicacao incremental
echo ----------------------------------------------------------
".venv\Scripts\python.exe" run_update_weni.py --apply
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro_apply

echo.
echo ==========================================================
echo [OK] NexoFlow Weni concluido com sucesso.
echo Auditoria: OK ^| Gravacao: OK
echo ==========================================================
echo.
pause
exit /b 0

:erro_checkup
echo.
echo [ERRO] Check-up falhou. Nenhuma alteracao foi feita na Weni.
pause
exit /b %RC%

:erro_conexoes
echo.
echo [ERRO] Teste de conexoes falhou. Nenhuma alteracao foi feita na Weni.
pause
exit /b %RC%

:erro_dryrun
echo.
echo [ERRO] Dry-run/auditoria falhou. Nenhuma alteracao foi feita na Weni.
pause
exit /b %RC%

:erro_apply
echo.
echo [ERRO] A aplicacao foi interrompida.
echo O checkpoint NAO foi avancado. Execute novamente apos corrigir o problema.
echo Consulte logs\nexoflow_update_weni.log e logs\weni_update_audit.jsonl.
pause
exit /b %RC%
