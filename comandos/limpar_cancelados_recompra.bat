@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
for %%I in ("%~dp0..") do set "NEXOFLOW_HOME=%%~fI"
set "PYTHONPATH=%NEXOFLOW_HOME%;%NEXOFLOW_HOME%\app;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PROFILE_LOG=logs"
set "IMPORT_DIR=importacoes"
if /i "%NEXOFLOW_PERFIL%"=="PET" set "PROFILE_LOG=logs\PET"
if /i "%NEXOFLOW_PERFIL%"=="PET" set "IMPORT_DIR=importacoes\PET"
cd /d "%NEXOFLOW_HOME%\"
title NexoFlow - Limpar cancelados da Recompra
echo [1] FarmaLíder D+25
echo [2] Pets Líder D+30
choice /c 12 /n /m "Escolha o segmento: "
if errorlevel 3 goto :cancelar
if errorlevel 2 goto :pet
set "PROFILE=FARMA"
set "PROFILE_LOG=logs"
goto :iniciar
set "NEXOFLOW_PERFIL=%PROFILE%"
:pet
set "PROFILE=PET"
set "PROFILE_LOG=logs\PET"
:iniciar
set "NEXOFLOW_PERFIL=%PROFILE%"
set "RC=1"
set "REVIEW=%PROFILE_LOG%\recompra_cancelados_%RANDOM%_%RANDOM%.json"
echo Esta rotina apenas remove cancelados do grupo de Recompra.
echo Não exclui contatos, não altera campos e não envia mensagens.
".venv\Scripts\python.exe" app\run_recompra.py --perfil %PROFILE% --cleanup-cancelled --dry-run --review-out "%REVIEW%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :fim
start "" notepad.exe "%CD%\%REVIEW:.json=.txt%"
if errorlevel 1 goto :cancelar
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%NEXOFLOW_HOME%\scripts\confirmar_revisao_weni.ps1" -Expected "LIMPEZA REVISADA" -Title "NexoFlow - Revisão dos cancelados"
if errorlevel 1 goto :cancelar
".venv\Scripts\python.exe" app\run_recompra.py --perfil %PROFILE% --cleanup-cancelled --apply --require-review "%REVIEW%"
set "RC=%ERRORLEVEL%"
goto :fim
:cancelar
set "RC=1"
echo [AVISO] Limpeza não iniciada ou cancelada.
:fim
if "%RC%"=="0" echo [OK] Limpeza concluída.
if "%RC%"=="3" echo [AVISO] Limpeza concluída com pendências. Gere uma nova revisão para revalidar.
if not "%RC%"=="0" if not "%RC%"=="3" echo [ERRO] Limpeza interrompida. Preserve o relatório e a auditoria.
pause
exit /b %RC%
