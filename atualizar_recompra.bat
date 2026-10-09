@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
title NexoFlow 1.0 - Recompra FarmaLíder
set "REVIEW_JSON=logs\recompra_review.json"
set "REVIEW_TXT=logs\recompra_review.txt"
".venv\Scripts\python.exe" run_recompra.py --check-only
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :fim
".venv\Scripts\python.exe" run_recompra.py --dry-run --review-out "%REVIEW_JSON%"
set "RC=%ERRORLEVEL%"
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
:fim
if not "%RC%"=="0" echo [AVISO] Recompra não concluída. Não repita uma inclusão indeterminada sem investigar o estado.
if not defined NEXOFLOW_LAUNCHER pause
exit /b %RC%
