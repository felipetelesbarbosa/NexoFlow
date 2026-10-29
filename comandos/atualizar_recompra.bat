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
set "STRICT_ARG="
cd /d "%NEXOFLOW_HOME%\"
title NexoFlow 1.0 - Recompra FarmaLíder
set "PROFILE=FARMA"
if /i "%NEXOFLOW_PERFIL%"=="PET" set "PROFILE=PET"
set "PROFILE_LOG=logs"
if /i "%NEXOFLOW_PERFIL%"=="PET" set "PROFILE_LOG=logs\PET"
if /i "%~1"=="PET" set "PROFILE=PET"
if /i "%~1"=="PET" set "NEXOFLOW_PERFIL=PET"
if /i "%~1"=="PET" set "PROFILE_LOG=logs\PET"
if /i "%~1"=="PET" title NexoFlow 1.0 - Recompra Pets Líder
set "REVIEW_JSON=%PROFILE_LOG%\recompra_review.json"
set "REVIEW_TXT=%PROFILE_LOG%\recompra_review.txt"
set "REVIEW_REFRESHES=0"
set "APPLY_FINISHED=0"
".venv\Scripts\python.exe" app\run_recompra.py --check-only --perfil %PROFILE%
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :fim
:gerar_revisao
".venv\Scripts\python.exe" app\run_recompra.py --dry-run %STRICT_ARG% --review-out "%REVIEW_JSON%" --perfil %PROFILE%
set "RC=%ERRORLEVEL%"
if "%RC%"=="4" goto :renovar_revisao
if not "%RC%"=="0" goto :fim
".venv\Scripts\python.exe" app\run_recompra.py --check-review --require-review "%REVIEW_JSON%" --perfil %PROFILE%
set "RC=%ERRORLEVEL%"
if "%RC%"=="4" goto :renovar_revisao
if not "%RC%"=="0" goto :fim
start "" notepad.exe "%CD%\%REVIEW_TXT%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :fim
echo Revise as inclusões e remoções. O envio permanece na campanha Weni.
echo A confirmação será solicitada em uma janela separada.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%NEXOFLOW_HOME%\scripts\confirmar_revisao_weni.ps1" -Expected "RECOMPRA REVISADA" -Title "NexoFlow - Revisão de Recompra"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :fim
".venv\Scripts\python.exe" app\run_recompra.py --apply --require-review "%REVIEW_JSON%" --perfil %PROFILE%
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" set "APPLY_FINISHED=1"
if "%RC%"=="3" set "APPLY_FINISHED=1"
if "%RC%"=="4" goto :renovar_revisao
goto :fim
:renovar_revisao
if "%REVIEW_REFRESHES%"=="1" goto :fim
set "REVIEW_REFRESHES=1"
set "REVIEW_JSON=%PROFILE_LOG%\recompra_review_renovada_%RANDOM%_%RANDOM%.json"
set "REVIEW_TXT=%REVIEW_JSON:.json=.txt%"
echo [INFO] O dia mudou antes da aplicação. Gerando uma revisão atualizada.
echo [INFO] O novo relatório precisa ser revisado e confirmado novamente.
goto :gerar_revisao
:fim
if "%RC%"=="0" (
    echo [OK] Recompra concluída.
) else if "%RC%"=="3" (
    if "%APPLY_FINISHED%"=="1" (
        echo [AVISO] Recompra concluída com pendências. As alterações confirmadas foram preservadas.
        echo Gere uma nova revisão na próxima execução para revalidar os contatos pendentes.
        echo Não reaplique a revisão antiga nem apague o estado ou a auditoria.
    ) else (
        echo [AVISO] Há consultas pendentes na preparação. A aplicação não foi iniciada nesta tentativa.
        echo Consulte a revisão e gere uma nova simulação antes de aplicar.
    )
) else if "%RC%"=="4" (
    echo [AVISO] A revisão expirou novamente. Nenhuma aplicação foi iniciada nesta tentativa. Execute a rotina novamente no dia atual.
) else if not "%RC%"=="0" (
    echo [ERRO] Recompra interrompida. Confira a auditoria e preserve o estado antes de retomar.
)
if not defined NEXOFLOW_LAUNCHER pause
exit /b %RC%
