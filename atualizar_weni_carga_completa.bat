@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title NexoFlow Weni - Carga Completa
set "NEXOFLOW_LAUNCHER=1"

cls
echo ==========================================================
echo NexoFlow Weni - Carga Completa
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
echo Elas usam a mesma base congelada e devem ser executadas em ordem.
echo Cada parte gera seu proprio dry-run, relatorio e snapshot revisavel.
echo.
set "OPCAO="
set /p "OPCAO=Opcao: " < CON

set "PART="
set "PART_ARG="
set "REVIEW_JSON=logs\weni_update_review_full.json"
set "REVIEW_TXT=logs\weni_update_review_full.txt"

if "%OPCAO%"=="0" goto :configurado
if "%OPCAO%"=="1" set "PART=1"
if "%OPCAO%"=="2" set "PART=2"
if "%OPCAO%"=="3" set "PART=3"
if "%OPCAO%"=="4" set "PART=4"
if not defined PART (
    echo [ERRO] Opcao invalida.
    pause < CON
    exit /b 2
)

set "PART_ARG=--quarter %PART%"
set "REVIEW_JSON=logs\weni_update_review_full_25_parte_%PART%.json"
set "REVIEW_TXT=logs\weni_update_review_full_25_parte_%PART%.txt"

:configurado
echo.
if defined PART (
    echo [INFO] Carga completa Weni 25%% - Parte %PART%/4.
) else (
    echo [INFO] Carga completa Weni tradicional - 100%%.
)
echo.
echo SEGURANCA NexoFlow 1.0 - ATENDIMENTO 24H:
echo   1. check-up
echo   2. teste de acesso
echo   3. dry-run + auditoria + snapshot congelado
echo   4. revisao humana
echo   5. apply EXATAMENTE do snapshot revisado
echo   6. validacao individual antes de cada contato
echo.
if defined PART (
    echo Na carga 25%%, somente os contatos da Parte %PART%/4 entram no plano.
    echo A proxima parte reutiliza o mesmo manifesto congelado.
) else (
    echo Esta rotina reanalisa 100%% da base disponivel.
)
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
echo [ETAPA 3/6] Dry-run + auditoria + snapshot congelado
echo ----------------------------------------------------------
".venv\Scripts\python.exe" run_update_weni.py --dry-run --full %PART_ARG% --review-out "%REVIEW_JSON%"
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
if defined PART echo Parte revisada: %PART%/4
echo O relatorio sera aberto no Bloco de Notas.
echo Confira especialmente LGPD, idade/maioridade, grupos, CPF e pedidos.
echo O plano fica congelado enquanto voce revisa.
echo O CMD ficara aguardando a confirmacao enquanto voce revisa.
echo Depois de concluir, feche o Bloco de Notas e volte ao CMD.
echo.
rem Nao usar START /WAIT: o Bloco de Notas moderno pode usar processo intermediario
rem e encerrar/alterar a espera do console. A confirmacao abaixo bloqueia no CON.
start "" notepad.exe "%CD%\%REVIEW_TXT%"

echo.
echo [ETAPA 4/6] Confirmacao humana
echo ----------------------------------------------------------
echo [INFO] O CMD permanecera aguardando uma confirmacao em janela separada.
set "CONFIRM_PART="
if defined PART set "CONFIRM_PART=-Part %PART%"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\confirmar_revisao_weni.ps1" %CONFIRM_PART%
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo [INFO] Operacao cancelada. Nenhuma alteracao foi aplicada.
    exit /b 2
)

echo.
echo [ETAPA 5/6] Aplicando snapshot congelado com validacao por contato
echo ----------------------------------------------------------
".venv\Scripts\python.exe" run_update_weni.py --apply --full %PART_ARG% --require-review "%REVIEW_JSON%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro

echo.
echo [ETAPA 6/6] Carga concluida
echo ==========================================================
if defined PART (
    echo [OK] Parte %PART%/4 concluida.
    if not "%PART%"=="4" echo Execute a proxima parte quando desejar.
    if "%PART%"=="4" echo [OK] As quatro partes Weni foram concluídas nesta campanha.
) else (
    echo [OK] Carga completa 100%% concluida.
)
echo Relatorio: %REVIEW_TXT%
echo Snapshot:  %REVIEW_JSON%
echo Manifesto 25%%: logs\full_load_25_manifest.json
echo ==========================================================
pause < CON
exit /b 0

:erro
echo.
echo [ERRO] Processo interrompido. Nenhuma etapa posterior deve ser presumida como concluida.
if defined PART echo [INFO] A Parte %PART%/4 NAO deve ser presumida como concluida.
echo Consulte logs\nexoflow_update_weni.log.
pause < CON
exit /b %RC%
