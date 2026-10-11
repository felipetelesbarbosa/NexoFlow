@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
set "PYTHONIOENCODING=utf-8"
set "STRICT_ARG="
if defined NEXOFLOW_FULL_WORKFLOW set "STRICT_ARG=--require-complete"
cd /d "%~dp0"
title NexoFlow 1.0 - Recompra FarmaLíder
set "REVIEW_JSON=logs\recompra_review.json"
set "REVIEW_TXT=logs\recompra_review.txt"
set "REVIEW_REFRESHES=0"
".venv\Scripts\python.exe" run_recompra.py --check-only
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :fim
:gerar_revisao
".venv\Scripts\python.exe" run_recompra.py --dry-run %STRICT_ARG% --review-out "%REVIEW_JSON%"
set "RC=%ERRORLEVEL%"
if "%RC%"=="4" goto :renovar_revisao
if not "%RC%"=="0" goto :fim
".venv\Scripts\python.exe" run_recompra.py --check-review --require-review "%REVIEW_JSON%"
set "RC=%ERRORLEVEL%"
if "%RC%"=="4" goto :renovar_revisao
if not "%RC%"=="0" goto :fim
start "" notepad.exe "%CD%\%REVIEW_TXT%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :fim
echo Revise as inclusões e remoções. O envio permanece na campanha Weni.
echo A confirmação será solicitada em uma janela separada.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0scripts\confirmar_revisao_weni.ps1" -Expected "RECOMPRA REVISADA" -Title "NexoFlow - Revisão de Recompra"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :fim
".venv\Scripts\python.exe" run_recompra.py --apply --require-review "%REVIEW_JSON%"
set "RC=%ERRORLEVEL%"
if "%RC%"=="4" goto :renovar_revisao
goto :fim
:renovar_revisao
if "%REVIEW_REFRESHES%"=="1" goto :fim
set "REVIEW_REFRESHES=1"
set "REVIEW_JSON=logs\recompra_review_renovada_%RANDOM%_%RANDOM%.json"
set "REVIEW_TXT=%REVIEW_JSON:.json=.txt%"
echo [INFO] O dia mudou antes da aplicação. Gerando uma revisão atualizada.
echo [INFO] O novo relatório precisa ser revisado e confirmado novamente.
goto :gerar_revisao
:fim
if "%RC%"=="4" (
    echo [AVISO] A revisão expirou novamente. Nenhuma aplicação foi iniciada nesta tentativa. Execute a rotina novamente no dia atual.
) else if not "%RC%"=="0" (
    echo [AVISO] Recompra não concluída. Confira a auditoria e o estado antes de retomar.
)
if not defined NEXOFLOW_LAUNCHER pause
exit /b %RC%
