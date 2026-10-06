@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title NexoFlow Weni - Carga Completa
set "NEXOFLOW_LAUNCHER=1"
set "REVIEW_JSON=logs\weni_update_review_full.json"
set "REVIEW_TXT=logs\weni_update_review_full.txt"

cls
echo ==========================================================
echo NexoFlow Weni - Carga Completa
echo ==========================================================
echo.
echo Esta rotina reanalisa o historico disponivel de mensagens e contatos.
echo Use na primeira carga ou quando precisar reconstruir os campos.
echo.
echo SEGURANCA NexoFlow 1.0 - ATENDIMENTO 24H:
echo   1. dry-run completo
echo   2. auditoria automatica obrigatoria
echo   3. plano congelado + relatorio para revisao humana
echo   4. confirmacao manual
echo   5. apply EXATAMENTE do snapshot revisado
echo   6. validacao individual imediatamente antes de cada contato
echo   7. contato alterado durante a revisao = conflito isolado, nao cancela a carga
echo.
echo Novas mensagens e novos contatos nao invalidam o snapshot revisado.
echo Eles serao capturados pela proxima execucao incremental.
echo.

call "%~dp0check-up.bat"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro

call "%~dp0testar_update_weni.bat"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro

if exist "%REVIEW_JSON%" del /q "%REVIEW_JSON%" >nul 2>&1
if exist "%REVIEW_TXT%" del /q "%REVIEW_TXT%" >nul 2>&1

echo.
echo [ETAPA 3/6] Dry-run completo + auditoria + snapshot congelado
echo ----------------------------------------------------------
".venv\Scripts\python.exe" run_update_weni.py --dry-run --full --review-out "%REVIEW_JSON%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro

if not exist "%REVIEW_JSON%" (
    echo [ERRO] Snapshot de revisao nao foi gerado: %REVIEW_JSON%
    set "RC=3"
    goto :erro
)
if not exist "%REVIEW_TXT%" (
    echo [ERRO] Relatorio de revisao nao foi gerado: %REVIEW_TXT%
    set "RC=3"
    goto :erro
)

echo.
echo ==========================================================
echo REVISAO HUMANA OBRIGATORIA
echo ==========================================================
echo O relatorio sera aberto no Bloco de Notas.
echo Confira especialmente LGPD, idade/maioridade, grupos, CPF e pedidos.
echo O plano fica congelado enquanto voce revisa.
echo Novos atendimentos nao obrigam refazer toda a carga.
echo Feche o Bloco de Notas somente depois de concluir a revisao.
echo.
start "" /wait notepad.exe "%CD%\%REVIEW_TXT%"

echo.
echo [ETAPA 4/6] Confirmacao humana
echo ----------------------------------------------------------
set /p "CONFIRMA=Digite CARGA COMPLETA REVISADA para aplicar exatamente o snapshot revisado: "
if /I not "%CONFIRMA%"=="CARGA COMPLETA REVISADA" (
    echo [INFO] Operacao cancelada. Nenhuma alteracao foi aplicada.
    pause
    exit /b 2
)

echo.
echo [ETAPA 5/6] Aplicando snapshot congelado com validacao por contato
echo ----------------------------------------------------------
".venv\Scripts\python.exe" run_update_weni.py --apply --full --require-review "%REVIEW_JSON%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro

echo.
echo [ETAPA 6/6] Carga completa concluida
echo ==========================================================
echo [OK] O snapshot revisado foi processado sem recalcular o historico.
echo Contatos que mudaram durante a revisao foram ignorados individualmente
echo e serao reavaliados pela proxima execucao incremental.
echo Relatorio: %REVIEW_TXT%
echo Snapshot:  %REVIEW_JSON%
echo ==========================================================
pause
exit /b 0

:erro
echo.
echo [ERRO] Processo interrompido. Nenhuma etapa posterior deve ser presumida como concluida.
echo Consulte logs\nexoflow_update_weni.log.
pause
exit /b %RC%
